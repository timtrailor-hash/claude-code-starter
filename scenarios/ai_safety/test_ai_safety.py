"""AI-specific safety scenarios.

Added 2026-04-21 after memory poisoning research (Cisco) and MCP STDIO
vulnerability (OX Security). These tests close the class of gap traditional
pen-testing misses.

Design property 1: memory retrieval returns via tool-call results, never via
system-prompt injection. Defends against Cisco-class memory poisoning.

Design property 2: MCP servers installed from npm registries are version-pinned.
Defends against silent supply-chain drift.

Design property 3: no code path in the tree promotes retrieved content into the
system message role. If this test fails a session could be poisoned by a
planted memory entry.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest


HOME = Path.home()
CODE = HOME / "code"
CLAUDE = HOME / ".claude"


def test_memory_server_returns_strings_via_tool_decorator():
    """search_memory and search_exact must be @mcp.tool() functions returning
    strings. This is the design property that keeps retrieved content in the
    low-authority tool-result lane rather than the system prompt."""
    src = (CODE / "memory_server.py").read_text()

    for fn in ("search_memory", "search_exact"):
        # Find the function definition
        m = re.search(rf"@mcp\.tool\(\).*?def {fn}\(", src, re.DOTALL)
        assert m is not None, (
            f"{fn} must be decorated with @mcp.tool() so results land in "
            f"the tool-result lane, not the system prompt"
        )
        # Return annotation must be str
        m2 = re.search(rf"def {fn}\([^)]*\)\s*->\s*str", src)
        assert m2 is not None, (
            f"{fn} must return str (so callers treat it as a string tool "
            f"result, not a structured system-injectable payload)"
        )


def test_no_retrieval_to_system_prompt_path():
    """Guard: no code path in ~/code may route retrieval output (search_memory,
    search_exact, or ChromaDB collection.query results) into a messages list
    with role='system'. If this test fails a future refactor may have opened
    the Cisco-class vulnerability."""
    forbidden_patterns = [
        # "system" role paired with search output
        (r'"role":\s*"system".*search_memory', "search_memory into system role"),
        (r'"role":\s*"system".*search_exact', "search_exact into system role"),
        (r'"role":\s*"system".*collection\.query', "ChromaDB query into system role"),
    ]
    offenders = []
    for py in CODE.rglob("*.py"):
        # Skip the test files themselves
        if "test_" in py.name or "__pycache__" in str(py):
            continue
        # Skip third-party vendored code
        if "/.venv/" in str(py) or "/venv/" in str(py):
            continue
        try:
            content = py.read_text()
        except Exception:
            continue
        for pat, desc in forbidden_patterns:
            if re.search(pat, content, re.DOTALL):
                offenders.append(f"{py}: {desc}")

    assert not offenders, (
        "Retrieval content must not be routed into system-role messages. "
        "Offending paths:\n" + "\n".join(offenders)
    )


def test_mcp_npm_servers_version_pinned():
    """Guard: every MCP server installed via npx must specify a pinned version.
    Unpinned @latest pulls are a silent supply-chain attack surface."""
    settings_path = CLAUDE / "settings.json"
    if not settings_path.exists():
        pytest.skip("no settings.json on this host")

    cfg = json.loads(settings_path.read_text())
    mcp = cfg.get("mcpServers", {})
    assert mcp, "expected MCP servers to be declared"

    unpinned = []
    for name, server in mcp.items():
        cmd = server.get("command", "")
        args = server.get("args", [])
        if cmd != "npx":
            continue  # non-npm MCPs out of scope for this test
        # For npx -y <package>, the package comes after -y
        # Every argument that looks like an @scoped/package or a package
        # name must contain an @version pin.
        for a in args:
            if a.startswith("-"):
                continue
            if a.startswith("/") or a.startswith("."):
                continue  # path arg, not a package spec
            # Package spec: look for @<version> at the tail.
            # Scoped packages have form @scope/name or @scope/name@version.
            if a.startswith("@"):
                # Scoped: "@scope/name" vs "@scope/name@ver"
                parts = a.split("@")
                # Valid pinned: "@scope/name@ver" -> ["", "scope/name", "ver"]
                pinned = len(parts) >= 3 and parts[2]
            else:
                pinned = "@" in a and not a.endswith("@")
            if not pinned and "/" in a:
                # It's a package spec without a pin
                unpinned.append(f"{name}: {a}")

    assert not unpinned, (
        "MCP npm packages must be pinned to an explicit version "
        "(use package@x.y.z, not just package):\n" + "\n".join(unpinned)
    )


def test_memory_retrieval_provenance_visible():
    """Guard: search_memory formats results with metadata (conv_id, date, topic)
    so a human reading retrieved content can see where it came from. Defends
    against injected content masquerading as trusted memory."""
    src = (CODE / "memory_server.py").read_text()

    # Look for the formatting block in search_memory
    # Must include at minimum: date, topic, and source id
    required_metadata_fields = ["conv_id", "date", "topic"]

    for field in required_metadata_fields:
        assert f"'{field}'" in src or f'"{field}"' in src, (
            f"search_memory output must surface {field!r} metadata so "
            f"retrieved content is visibly attributable"
        )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
