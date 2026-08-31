from __future__ import annotations
import argparse
from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["run", "check"]); args = parser.parse_args()
    config = load_config()
    try: config.validate_prerequisites()
    except ValueError as exc:
        print(f"voice unavailable: {exc}"); return 2
    if args.command == "check": return 0
    print("voice service adapters require runtime construction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
