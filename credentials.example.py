"""Example credentials loader.

Copy to credentials.py and fill in, OR (recommended) use macOS Keychain
with the loader pattern below. The keychain approach keeps secrets out of
any file you might accidentally commit.

Keychain seed (run once per secret):
    security add-generic-password -a ANTHROPIC_API_KEY -s my-credentials -w <key> -U
    security add-generic-password -a GEMINI_API_KEY    -s my-credentials -w <key> -U
    security add-generic-password -a OPENAI_API_KEY    -s my-credentials -w <key> -U
    security add-generic-password -a PERPLEXITY_API_KEY -s my-credentials -w <key> -U
"""

import os
import subprocess

_SERVICE = 'my-credentials'
_KEYCHAIN = os.path.expanduser('~/Library/Keychains/login.keychain-db')

def _get(name):
    r = subprocess.run(
        ['security', 'find-generic-password', '-a', name, '-s', _SERVICE, '-w', _KEYCHAIN],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ''

ANTHROPIC_API_KEY   = _get('ANTHROPIC_API_KEY')
GEMINI_API_KEY      = _get('GEMINI_API_KEY')
OPENAI_API_KEY      = _get('OPENAI_API_KEY')
PERPLEXITY_API_KEY  = _get('PERPLEXITY_API_KEY')

# Optional: Simple Mail Transfer Protocol credentials for email sends
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = _get('SMTP_PASS')
