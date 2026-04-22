"""Shared fixtures for the safety scenario test suite."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def settings_json():
    """Load the current settings.json."""
    settings_path = Path.home() / ".claude" / "settings.json"
    with open(settings_path) as f:
        return json.load(f)


@pytest.fixture
def hooks_dir():
    """Path to the hooks directory."""
    return Path.home() / ".claude" / "hooks"


@pytest.fixture
def printer_safety_module():
    """Import printer_safety.py as a module for testing."""
    hooks = Path.home() / ".claude" / "hooks"
    sys.path.insert(0, str(hooks))
    try:
        # Reload to pick up fresh config each time
        import importlib
        import printer_safety
        importlib.reload(printer_safety)
        return printer_safety
    finally:
        sys.path.pop(0)


@pytest.fixture
def mock_moonraker():
    """Fixture that patches printer_safety to return a mocked printer state."""
    class MockMoonraker:
        def __init__(self):
            self.state = "printing"

        def set_state(self, state):
            self.state = state

    mock = MockMoonraker()
    yield mock


def run_hook(hook_name, stdin_json, hooks_dir=None):
    """Run a hook script with JSON on stdin and return (stdout, stderr, returncode)."""
    if hooks_dir is None:
        hooks_dir = Path.home() / ".claude" / "hooks"
    script = hooks_dir / hook_name
    assert script.exists(), f"Hook {hook_name} not found at {script}"
    proc = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout, proc.stderr, proc.returncode
