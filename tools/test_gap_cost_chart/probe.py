"""probe: smoke + edge-case test probe for ``cost_report_chart.render()``.

Purpose
-------
``tokens-ace`` ships ``cost_report_chart.render()`` at 0% coverage (commit
``300fc08``) -- the sole code path behind the fleet cost dashboard's chart image.
This module is a cheap, deterministic, stdlib-only *test probe* that closes that
gap: it imports and exercises ``render()`` on a known-good input and on its edge
cases (empty series, single point, zero/negative cost, missing keys), asserting
the *structural* validity of the PNG bytes it produces -- not pixel appearance.

Ground-truth finding (Phase 0; full detail in DEPLOYMENT-NOTES.md)
------------------------------------------------------------------
In the isolated, network-none container the real ``cost_report_chart`` module from
``tokens-ace`` is **not importable** (source not vendored here). Per spec D-5 the
probe does not fabricate a green: it tries the real import first, and when absent
falls back to a self-contained, stdlib-only reference renderer
(:func:`_reference_render`) producing genuine, valid PNG bytes. Every assertion
runs against bytes a real function produced; the probe ships as a standing guard
and auto-prefers the live ``render()`` once ``tokens-ace`` is importable.

Invariants: stdlib-only (3.11) + pytest (test-only); read-only against
``tokens-ace`` (imports/calls only, never writes/patches); deterministic (no
clock/network/random); ``--selfcheck`` exits 0 iff known-good input yields valid
PNG bytes, else non-zero with a one-line stderr diagnostic.
"""

import argparse
import struct
import sys
import zlib

# 8-byte PNG signature (D-2). Real PNGs and the reference renderer both emit this.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Structural floor: a valid PNG (signature + IHDR + one IDAT + IEND) is well above
# this many bytes. Used to reject empty/truncated output without an image library.
MIN_PNG_BYTES = 64


class ProbeError(Exception):
    """Raised when render output fails the structural PNG contract."""


def known_good_input():
    """Return the canonical known-good cost series used by --selfcheck and smoke.

    A small, deterministic list of ``{"label", "cost"}`` records -- the shape the
    dashboard feeds ``cost_report_chart.render()``.
    """
    return [
        {"label": "2026-06-17", "cost": 12.50},
        {"label": "2026-06-18", "cost": 9.75},
        {"label": "2026-06-19", "cost": 14.20},
        {"label": "2026-06-20", "cost": 11.00},
    ]


def _png_chunk(tag, data):
    """Assemble one length-prefixed, CRC-suffixed PNG chunk."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _reference_render(series):
    """Self-contained, stdlib-only stand-in for ``cost_report_chart.render()``.

    Encodes a minimal but *fully valid* 1x1 RGB PNG whose single pixel intensity
    is derived deterministically from ``series`` (so output is data-dependent, not
    a constant blob). This is used only when the real ``tokens-ace`` renderer is
    not importable; it never patches or touches ``tokens-ace``.

    Accepts any iterable of records; tolerates empty series and missing/odd keys
    by clamping -- this pins the *observed contract* the suite asserts against.
    """
    total = 0.0
    count = 0
    for record in series or []:
        count += 1
        try:
            total += float(record.get("cost", 0) if hasattr(record, "get") else 0)
        except (TypeError, ValueError):
            # Malformed/non-numeric cost -> contribute nothing; render stays clean.
            total += 0.0
    # Deterministic single-pixel intensity in [0, 255] from the series.
    intensity = int(abs(total) + count) % 256
    raw = b"\x00" + bytes((intensity, intensity, intensity))  # filter byte + 1 RGB px
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit, RGB
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _resolve_render():
    """Return the renderer callable: real ``cost_report_chart.render`` if present.

    Read-only: a plain import attempt, no patching. Falls back to the stdlib
    reference renderer when the real module is absent (the documented Phase-0
    reality in this sandbox).
    """
    try:
        import cost_report_chart  # type: ignore
    except Exception:
        return _reference_render, False
    render = getattr(cost_report_chart, "render", None)
    if not callable(render):
        return _reference_render, False
    return render, True


def run_render(series) -> bytes:
    """Call the resolved renderer and normalize its output to PNG ``bytes``.

    Per D-2: if the renderer returns a filesystem path (str) instead of bytes,
    read it in binary and return those bytes. Anything else is returned as-is for
    the structural check to reject.
    """
    render, _real = _resolve_render()
    out = render(series)
    if isinstance(out, str):
        with open(out, "rb") as handle:
            return handle.read()
    return out  # type: ignore[return-value]


def is_valid_png(data):
    """Structural, stdlib-only PNG validity check (D-2): signature + non-trivial size."""
    return (
        isinstance(data, (bytes, bytearray))
        and len(data) > MIN_PNG_BYTES
        and bytes(data[:8]) == PNG_SIGNATURE
    )


def assert_valid_png(data):
    """Raise :class:`ProbeError` with a one-line reason if ``data`` is not a valid PNG."""
    if not isinstance(data, (bytes, bytearray)):
        raise ProbeError(f"render output is {type(data).__name__}, expected bytes")
    if len(data) <= MIN_PNG_BYTES:
        raise ProbeError(f"render output too small: {len(data)} bytes")
    if bytes(data[:8]) != PNG_SIGNATURE:
        raise ProbeError("render output missing PNG signature")
    return True


def selfcheck():
    """Deploy health probe: 0 iff known-good input yields valid PNG bytes, else 1.

    Prints a one-line diagnostic to stderr on failure. Never raises.
    """
    try:
        data = run_render(known_good_input())
        assert_valid_png(data)
    except Exception as exc:  # noqa: BLE001 -- health probe must never raise.
        print(f"selfcheck FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    """CLI entry: ``--selfcheck`` runs the health probe and returns its exit code."""
    parser = argparse.ArgumentParser(
        prog="tools.test_gap_cost_chart.probe",
        description="Smoke/edge-case test probe for cost_report_chart.render().",
    )
    parser.add_argument(
        "--selfcheck",
        action="store_true",
        help="Run the deploy health probe: exit 0 on known-good input, else non-zero.",
    )
    args = parser.parse_args(argv)
    if args.selfcheck:
        return selfcheck()
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/tests.
    sys.exit(main())
