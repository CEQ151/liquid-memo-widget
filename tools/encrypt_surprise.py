"""Create the public surprise.enc from a git-ignored private JSON file."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "LiquidMemoWidget"
sys.path.insert(0, str(APP_DIR))

from surprise_crypto import encrypt_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="git-ignored private payload JSON")
    parser.add_argument("--output", type=Path, default=APP_DIR / "surprise.enc")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload.get("notes"), list) or not payload["notes"]:
        raise SystemExit("payload needs a non-empty notes list")
    password = getpass.getpass("Long passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if password != confirm:
        raise SystemExit("passphrases do not match")
    if len(password) < 12:
        raise SystemExit("passphrase must contain at least 12 characters")
    encrypted = encrypt_payload(payload, password)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(args.output)
    print(f"Wrote encrypted payload: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
