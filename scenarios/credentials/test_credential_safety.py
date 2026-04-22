"""
Credential safety scenario tests.

Source: security.md rules — no secrets in tracked files.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path.home() / ".claude" / "hooks"


def _run_credential_hook(file_path, content):
    """Run credential_leak_hook.sh with simulated Write input."""
    hook_input = {
        "tool_input": {
            "file_path": file_path,
            "content": content,
        }
    }
    proc = subprocess.run(
        ["bash", str(HOOKS_DIR / "credential_leak_hook.sh")],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc.stdout, proc.stderr, proc.returncode


class TestCredentialLeakPrevention:
    """Credential patterns in tracked files must be blocked."""

    def test_sec001_blocks_anthropic_api_key(self, tmp_path):
        """SEC-001: writing a file containing an Anthropic API key pattern."""
        test_file = str(tmp_path / "test.py")
        # Create a git repo so the hook sees it as tracked
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        with open(test_file, "w") as f:
            f.write("x = 1")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)

        content = 'ANTHROPIC_API_KEY = "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxx"'
        _, _, rc = _run_credential_hook(test_file, content)
        assert rc == 2, f"Should block API key pattern (rc={rc})"

    def test_sec002_allows_gitignored_files(self, tmp_path):
        """SEC-002: writing secrets to a gitignored file should be allowed."""
        test_file = str(tmp_path / "credentials.py")
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        with open(tmp_path / ".gitignore", "w") as f:
            f.write("credentials.py\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)

        content = 'API_KEY = "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxx"'
        _, _, rc = _run_credential_hook(test_file, content)
        assert rc == 0, f"Gitignored file should be allowed (rc={rc})"

    def test_sec003_allows_non_git_files(self, tmp_path):
        """SEC-003: files not in a git repo should be allowed."""
        test_file = "/tmp/scratch_test_file.py"
        content = 'API_KEY = "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxx"'
        _, _, rc = _run_credential_hook(test_file, content)
        assert rc == 0, f"Non-git file should be allowed (rc={rc})"


class TestProtectedPathHook:
    """Protected path hook blocks dangerous system operations."""

    def test_sec010_blocks_launchctl_load(self):
        """SEC-010: launchctl load must be blocked."""
        hook_input = {"tool_input": {"command": "launchctl load ~/Library/LaunchAgents/test.plist"}, "tool_name": "Bash"}
        proc = subprocess.run(
            ["bash", str(HOOKS_DIR / "protected_path_hook.sh")],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0 and '"permissionDecision": "ask"' in proc.stdout, (
            f"launchctl load should emit ask-decision (rc={proc.returncode}, stdout={proc.stdout!r})"
        )

    def test_sec011_blocks_sudo_reboot(self):
        """SEC-011: sudo reboot must be blocked."""
        hook_input = {"tool_input": {"command": "sudo reboot"}, "tool_name": "Bash"}
        proc = subprocess.run(
            ["bash", str(HOOKS_DIR / "protected_path_hook.sh")],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0 and '"permissionDecision": "ask"' in proc.stdout, (
            f"sudo reboot should emit ask-decision (rc={proc.returncode}, stdout={proc.stdout!r})"
        )
