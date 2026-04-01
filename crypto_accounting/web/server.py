"""
Launch the Crypto Accounting web server.

Usage::

    python -m crypto_accounting.web.server           # http://localhost:8000
    python -m crypto_accounting.web.server --port 9000 --host 0.0.0.0
"""

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Crypto Accounting Web Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    print(f"Starting Crypto Accounting at http://{args.host}:{args.port}")
    uvicorn.run(
        "crypto_accounting.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
