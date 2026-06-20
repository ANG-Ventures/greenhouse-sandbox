#!/usr/bin/env python3.11
"""Greenhouse green-path proof tool: a trivial, stdlib-only, deterministic reporter.
Off by default; --selfcheck is the deploy health probe. No state outside its own output.
"""
from __future__ import annotations
import argparse


def normalize(text: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends. Pure, deterministic."""
    return " ".join(text.split())


def selfcheck() -> int:
    """Known-good invariant: normalize is idempotent and collapses whitespace."""
    a = normalize("  hello   greenhouse \n world ")
    if a != "hello greenhouse world":
        return 1
    if normalize(a) != a:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="greenhouse green-path proof tool")
    ap.add_argument("--selfcheck", action="store_true", help="run the health self-check and exit")
    ap.add_argument("--text", default="", help="text to normalize")
    args = ap.parse_args(argv)
    if args.selfcheck:
        return selfcheck()
    print(normalize(args.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
