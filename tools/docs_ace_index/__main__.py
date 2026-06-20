"""CLI entrypoint: python -m tools.docs_ace_index ...

Usage:
  build [--manifest PATH] [--out PATH]   render manifest -> index.html
  --selfcheck                            deploy health probe (exit 0/1)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .index import ManifestError, build, selfcheck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docs_ace_index",
        description="Generate the docs.ace static dark-mode index.",
    )
    parser.add_argument(
        "--selfcheck",
        action="store_true",
        help="deploy health probe: exit 0 on known-good fixture, else 1",
    )
    sub = parser.add_subparsers(dest="command")
    build_p = sub.add_parser("build", help="render manifest.toml -> index.html")
    build_p.add_argument(
        "--manifest", type=Path, default=None, help="path to manifest.toml"
    )
    build_p.add_argument(
        "--out", type=Path, default=None, help="output HTML path"
    )

    args = parser.parse_args(argv)

    if args.selfcheck:
        ok = selfcheck()
        print("selfcheck: OK" if ok else "selfcheck: FAIL", file=sys.stderr)
        return 0 if ok else 1

    if args.command == "build":
        try:
            out = build(manifest=args.manifest, out=args.out)
        except ManifestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {out}")
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
