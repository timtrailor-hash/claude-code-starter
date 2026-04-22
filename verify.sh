#!/bin/bash
# verify.sh — system verification script
#
# Checks that all referenced hooks, MCPs, launchers exist and are executable.
# Runs critical safety scenario tests if pytest is available.
# Used as a gate by deploy.sh — deployment blocked if verify fails.
#
# Usage:
#   ./verify.sh           # full verify (hooks + scenarios)
#   ./verify.sh --quick   # hooks only (skip scenarios, for speed)

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
QUICK=0
for arg in "$@"; do
    [ "$arg" = "--quick" ] && QUICK=1
done

PASS=0
FAIL=0
WARN=0

check() {
    local desc="$1"
    local result="$2"  # 0=pass, 1=fail, 2=warn
    if [ "$result" = "0" ]; then
        PASS=$((PASS + 1))
    elif [ "$result" = "2" ]; then
        echo "  WARN: $desc"
        WARN=$((WARN + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== verify.sh ==="

# 1. Check all hooks referenced in settings.json exist
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    MISSING_HOOKS=$(python3 - "$SETTINGS" <<PYEOF
import json, sys, os, re
data = json.load(open(sys.argv[1]))
missing = []
# Only check tokens that look like executable scripts/binaries.
# Shell for-loops and dual-path-or patterns have other / tokens that
# are legitimately per-machine (e.g. /Users/.../-Documents-Claude-code
# vs /Users/.../-code) — those are NOT the hook we're validating.
EXE_SUFFIX = re.compile(r"\.(sh|py|pl|rb)$|/bin/[^/\s]+$")
for stage in data.get("hooks", {}).values():
    for entry in stage:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            for tok in cmd.split():
                if tok.startswith("/") and EXE_SUFFIX.search(tok):
                    if not os.path.exists(tok):
                        missing.append(tok)
                    break
for m in data.get("mcpServers", {}).values():
    cmd = m.get("command", "")
    if cmd.startswith("/") and EXE_SUFFIX.search(cmd) and not os.path.exists(cmd):
        missing.append(cmd)
for p in missing:
    print(p)
PYEOF
)
    if [ -z "$MISSING_HOOKS" ]; then
        check "all hook/MCP paths exist in settings.json" "0"
    else
        while IFS= read -r p; do
            check "path exists: $p" "1"
        done <<< "$MISSING_HOOKS"
    fi
else
    check "settings.json exists" "1"
fi

# 2. Check printer safety hook is wired
if grep -q "printer-safety-check" "$SETTINGS" 2>/dev/null; then
    check "printer-safety-check wired in settings.json" "0"
else
    check "printer-safety-check wired in settings.json" "1"
fi

# 3. keychain_pass presence policy — delegated to hosts/<host>.yaml forbidden_files.
#    Removed the hardcoded check on 2026-04-18: services.yaml documents
#    ~/.keychain_pass as the intentional accepted-risk root-of-trust bypass
#    for unlock-keychain.sh. If policy changes, re-add to forbidden_files.


# 4. Check critical binaries
for bin in /opt/homebrew/bin/python3.11 /opt/homebrew/bin/ruff /opt/homebrew/bin/semgrep /opt/homebrew/bin/swiftlint; do
    if [ -x "$bin" ]; then
        check "binary exists: $(basename $bin)" "0"
    else
        check "binary exists: $(basename $bin)" "2"
    fi
done

# 5. Memory health (quick functional probe)
if command -v python3.11 >/dev/null 2>&1 || [ -x /opt/homebrew/bin/python3.11 ]; then
    MEM_RESULT=$(/opt/homebrew/bin/python3.11 - <<MEMEOF 2>&1
import sys
try:
    import chromadb
    from pathlib import Path
    for p in [Path.home()/"code"/"memory_server_data"/"chroma", Path.home()/"code"/"memory_server"/"data"/"chroma"]:
        if p.exists():
            c = chromadb.PersistentClient(path=str(p))
            coll = c.get_or_create_collection("conversations", metadata={"hnsw:space":"cosine"})
            count = coll.count()
            if count > 0:
                print(f"OK:{count}")
                sys.exit(0)
    print("EMPTY")
except Exception as e:
    print(f"FAIL:{e}")
MEMEOF
)
    case "$MEM_RESULT" in
        OK:*) check "memory ChromaDB has $(echo $MEM_RESULT | cut -d: -f2) chunks" "0" ;;
        EMPTY) check "memory ChromaDB is empty" "2" ;;
        *) check "memory ChromaDB: $MEM_RESULT" "1" ;;
    esac
fi

# 6. Services manifest exists
if [ -f "$REPO_DIR/machines/mac-mini/services.yaml" ]; then
    check "services.yaml exists" "0"
else
    check "services.yaml exists" "1"
fi

# 6a. system_map.yaml schema validation (runs for BOTH machines' maps)
# A faulty source of truth is more dangerous than a distributed one.
if [ -x /opt/homebrew/bin/python3.11 ]; then
    for MACHINE_NAME in mac-mini laptop; do
        MAP_PATH="$REPO_DIR/machines/$MACHINE_NAME/system_map.yaml"
        if [ -f "$MAP_PATH" ]; then
            VALIDATE_OUT=$(SYSTEM_MAP_MACHINE="$MACHINE_NAME" \
                /opt/homebrew/bin/python3.11 "$REPO_DIR/shared/lib/system_map.py" validate 2>&1)
            VALIDATE_RC=$?
            if [ "$VALIDATE_RC" = "0" ]; then
                check "system_map.yaml ($MACHINE_NAME) schema valid" "0"
            else
                while IFS= read -r line; do
                    [ -n "$line" ] && check "system_map ($MACHINE_NAME): $line" "1"
                done <<< "$VALIDATE_OUT"
            fi
        fi
    done
fi

# 6b. system_map.yaml ↔ plists ↔ health_check.py three-way alignment
#
# Pattern 17 (observability drift): system_map.yaml is the declared source of
# truth (for both mac-mini and laptop). This check enforces that the services
# section matches the plist files on disk AND matches health_check.py's
# runtime list. When all three agree, no Phase-4-style deletion can silently
# break the monitor.
#
# This check always targets mac-mini's map (even from the laptop) because the
# services/plists/health_check triad only exists on mac-mini.
if command -v /opt/homebrew/bin/python3.11 >/dev/null 2>&1; then
    ALIGN_RESULT=$(SYSTEM_MAP_MACHINE=mac-mini /opt/homebrew/bin/python3.11 - "$REPO_DIR" <<'PYEOF' 2>&1
import os, sys, re, subprocess
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "shared" / "lib"))
import system_map

# Source of truth: system_map.yaml service labels
declared = set(system_map.service_labels())
declared_short = {lbl.replace("com.example.", "") for lbl in declared}

# Also load the deprecated list so we can flag any deprecated service that's
# still on disk or in the monitor.
deprecated_short = set()
for name, entry in (system_map.deprecated() or {}).items():
    deprecated_short.add(name)

# Plist basenames on disk in the controlplane repo
plist_dir = repo / "machines" / "mac-mini" / "launchagents"
plists = {p.stem.replace("com.example.", "")
          for p in plist_dir.glob("com.example.*.plist")}

# health_check.py LAUNCHAGENTS runtime value
if hc_path.exists():
    hc_text = hc_path.read_text()
else:
    try:
        hc_text = subprocess.check_output(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
            text=True, timeout=10)
    except Exception:
        hc_text = ""

monitored_short = set()
if hc_text:
    m = re.search(r"LAUNCHAGENTS\s*=\s*\[(.*?)\]", hc_text, re.DOTALL)
    if m:
        monitored_short = set(
            re.findall(r"com\.example\.([a-z][a-z0-9\-]*)", m.group(1))
        )

issues = []
if declared_short != plists:
    only_yaml = sorted(declared_short - plists)
    only_plists = sorted(plists - declared_short)
    issues.append(
        f"system_map.yaml vs plists: only_in_map={only_yaml} only_in_plists={only_plists}"
    )
if monitored_short and declared_short != monitored_short:
    only_yaml = sorted(declared_short - monitored_short)
    only_mon = sorted(monitored_short - declared_short)
    issues.append(
        f"system_map.yaml vs health_check.py LAUNCHAGENTS: only_in_map={only_yaml} only_in_monitor={only_mon}"
    )
if not monitored_short:
    issues.append("could not parse health_check.py LAUNCHAGENTS (mac-mini not reachable?)")

# Extra guard: no deprecated service may appear in plists or monitor
dep_on_disk = deprecated_short & plists
dep_in_monitor = deprecated_short & monitored_short
if dep_on_disk:
    issues.append(f"deprecated services still on disk: {sorted(dep_on_disk)}")
if dep_in_monitor:
    issues.append(f"deprecated services still in health_check monitor: {sorted(dep_in_monitor)}")

for i in issues:
    print(i)
PYEOF
)
    if [ -z "$ALIGN_RESULT" ]; then
        check "system_map.yaml ↔ plists ↔ health_check.py aligned" "0"
    else
        while IFS= read -r line; do
            [ -n "$line" ] && check "alignment drift: $line" "1"
        done <<< "$ALIGN_RESULT"
    fi
fi

# 6d. Schedule drift: system_map.yaml `mode` vs plist schedule keys.
#
# Pattern 17 redux (2026-04-12 health-check incident): the manifest declared
# `mode: StartInterval 3600` while the plist used StartCalendarInterval
# Hour=4, Minute=0. Nothing mechanically checked the two agreed, so the
# health-check probe silently ran once a day for months and the iOS app
# showed probe:health-check red.
#
# This check canonicalises both sides to a comparable tuple and fails on
# any mismatch. Covers KeepAlive, RunAtLoad, StartInterval, and
# StartCalendarInterval (daily + weekly) — the four forms actually used in
# mac-mini/system_map.yaml. plist parsing uses `plutil -convert json`, not
# XML regex.
if command -v /opt/homebrew/bin/python3.11 >/dev/null 2>&1; then
    SCHED_RESULT=$(SYSTEM_MAP_MACHINE=mac-mini /opt/homebrew/bin/python3.11 - "$REPO_DIR" <<'PYEOF' 2>&1
import json, re, subprocess, sys
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "shared" / "lib"))
import system_map

WEEKDAYS = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}

def parse_manifest_mode(mode):
    """Canonicalise a system_map.yaml `mode:` string.

    Returns (kind, detail) where detail is hashable/comparable, or raises
    ValueError on an unrecognised shape. The shapes are intentionally the
    ones that actually appear in mac-mini/system_map.yaml — unknown forms
    surface as drift so this check never silently passes a new shape.
    """
    if not mode or not isinstance(mode, str):
        raise ValueError(f"empty or non-string mode: {mode!r}")
    s = mode.strip()
    if s == "KeepAlive":
        return ("KeepAlive", None)
    if s == "RunAtLoad":
        return ("RunAtLoad", None)
    m = re.fullmatch(r"StartInterval\s+(\d+)", s)
    if m:
        return ("StartInterval", int(m.group(1)))
    # StartCalendarInterval forms:
    #   StartCalendarInterval HH:MM                (daily)
    #   StartCalendarInterval <Weekday> HH:MM      (weekly)
    m = re.fullmatch(r"StartCalendarInterval\s+(\d{1,2}):(\d{2})", s)
    if m:
        return ("StartCalendarInterval",
                (("Hour", int(m.group(1))), ("Minute", int(m.group(2)))))
    m = re.fullmatch(r"StartCalendarInterval\s+(\w+)\s+(\d{1,2}):(\d{2})", s)
    if m:
        wd = WEEKDAYS.get(m.group(1).lower())
        if wd is None:
            raise ValueError(f"unknown weekday in mode: {s!r}")
        return ("StartCalendarInterval",
                (("Hour", int(m.group(2))), ("Minute", int(m.group(3))),
                 ("Weekday", wd)))
    raise ValueError(f"unrecognised mode shape: {s!r}")

def parse_plist_schedule(plist_path):
    """Canonicalise a plist's schedule keys to the same tuple shape."""
    out = subprocess.check_output(
        ["plutil", "-convert", "json", "-o", "-", str(plist_path)],
        text=True)
    d = json.loads(out)
    if d.get("KeepAlive"):
        return ("KeepAlive", None)
    if "StartInterval" in d:
        return ("StartInterval", int(d["StartInterval"]))
    sci = d.get("StartCalendarInterval")
    if isinstance(sci, dict):
        # Only carry keys we know how to compare; Weekday is optional.
        parts = [("Hour", int(sci.get("Hour", 0))),
                 ("Minute", int(sci.get("Minute", 0)))]
        if "Weekday" in sci:
            parts.append(("Weekday", int(sci["Weekday"])))
        return ("StartCalendarInterval", tuple(parts))
    # Nothing schedule-ish beyond RunAtLoad → treat as RunAtLoad one-shot.
    if d.get("RunAtLoad"):
        return ("RunAtLoad", None)
    return ("Unknown", None)

plist_dir = repo / "machines" / "mac-mini" / "launchagents"
issues = []
checked = 0
for name, entry in (system_map.services() or {}).items():
    if not isinstance(entry, dict):
        continue
    mode = entry.get("mode")
    label = entry.get("label") or f"com.example.{name}"
    plist_path = plist_dir / f"{label}.plist"
    if not plist_path.exists():
        # Alignment check 6b already flags missing plists — don't
        # double-report here.
        continue
    try:
        manifest_canon = parse_manifest_mode(mode)
    except ValueError as e:
        issues.append(f"{name}: manifest mode parse failed: {e}")
        continue
    try:
        plist_canon = parse_plist_schedule(plist_path)
    except Exception as e:
        issues.append(f"{name}: plist parse failed: {e}")
        continue
    checked += 1
    if manifest_canon != plist_canon:
        issues.append(
            f"DRIFT {name}: manifest mode={mode!r} "
            f"(canon={manifest_canon}) vs plist={plist_canon}"
        )

if checked == 0 and not issues:
    issues.append("no services checked — system_map.services() empty?")

for i in issues:
    print(i)
PYEOF
)
    if [ -z "$SCHED_RESULT" ]; then
        check "system_map.yaml mode ↔ plist schedule aligned" "0"
    else
        while IFS= read -r line; do
            [ -n "$line" ] && check "schedule drift: $line" "1"
        done <<< "$SCHED_RESULT"
    fi
fi

# 6c. Host-role manifest drift (audit 2026-04-11 §4.6).
HOST_MANIFEST_SCRIPT="$REPO_DIR/shared/hooks/verify_host_manifest.sh"
if [ -x "$HOST_MANIFEST_SCRIPT" ]; then
    HOST_OUT=$("$HOST_MANIFEST_SCRIPT" 2>&1)
    HOST_RC=$?
    if [ "$HOST_RC" = "0" ]; then
        check "host manifest drift (current host)" "0"
    else
        while IFS= read -r line; do
            [ -n "$line" ] && check "host manifest: $line" "1"
        done <<< "$HOST_OUT"
    fi
fi

# 7. Run pytest scenarios (unless --quick)
if [ "$QUICK" = "0" ] && [ -d "$REPO_DIR/scenarios" ]; then
    if /opt/homebrew/bin/python3.11 -m pytest --version 2>/dev/null >/dev/null 2>&1; then
        echo "  Running safety scenarios..."
        if /opt/homebrew/bin/python3.11 -m pytest "$REPO_DIR/scenarios/" -q --tb=short 2>&1 | tail -5; then
            check "safety scenarios" "0"
        else
            check "safety scenarios" "1"
        fi
    else
        check "pytest not installed (scenarios skipped)" "2"
    fi
fi

echo
echo "Results: $PASS passed, $FAIL failed, $WARN warnings"
[ "$FAIL" -gt 0 ] && exit 1
exit 0
