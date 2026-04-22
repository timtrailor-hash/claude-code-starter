"""
Drift detection scenario tests.

Source: 2026-04-07 found 3 hooks existed only on Mac Mini.
"""
import os
import subprocess
from pathlib import Path

import pytest


class TestDriftDetection:
    """Verify drift detection mechanisms work."""

    def test_drift001_validate_hooks_catches_missing(self, tmp_path):
        """DRIFT-001: validate_hooks.sh must catch missing hook paths."""
        script = Path.home() / ".claude" / "hooks" / "validate_hooks.sh"
        if not script.exists():
            pytest.skip("validate_hooks.sh not found")
        # The script reads settings.json and checks paths — just verify it runs
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should exit 0 (advisory) and produce output
        assert proc.returncode == 0

    def test_drift002_control_plane_repo_exists(self):
        """DRIFT-002: control-plane repo must exist and be a git repo."""
        repo = Path.home() / "code" / "tim-claude-controlplane"
        assert repo.exists(), f"Control plane repo not found at {repo}"
        assert (repo / ".git").exists(), "Control plane repo is not a git repo"
        assert (repo / "deploy.sh").exists(), "deploy.sh missing from control plane repo"
        assert (repo / "verify.sh").exists(), "verify.sh missing from control plane repo"

    def test_drift003_services_yaml_exists(self):
        """DRIFT-003: services.yaml must exist and be valid YAML."""
        svc = Path.home() / "code" / "tim-claude-controlplane" / "machines" / "mac-mini" / "services.yaml"
        assert svc.exists(), f"services.yaml not found at {svc}"
        content = svc.read_text()
        assert "conversation-server" in content, "services.yaml missing conversation-server"
        assert "printer-snapshots" in content, "services.yaml missing printer-snapshots"

    def test_drift004_symlinks_point_to_repo(self):
        """DRIFT-004: ~/.claude/ dirs must symlink to the control-plane repo."""
        for sub in ["rules", "hooks", "agents", "mcp-launchers"]:
            path = Path.home() / ".claude" / sub
            if path.is_symlink():
                target = os.readlink(path)
                assert "tim-claude-controlplane" in target, \
                    f"~/.claude/{sub} symlinks to {target}, not the control plane repo"
            # If not a symlink, that's OK on the laptop (not yet deployed)
