"""
Vercel serverless entry point.

Vercel looks for a callable named `app` (or `handler`) in this file.
We re-export the FastAPI app from the crypto_accounting package.
"""

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so the package can be imported
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from crypto_accounting.web.app import app  # noqa: E402  re-export for Vercel
