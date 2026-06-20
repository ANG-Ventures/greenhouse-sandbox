"""Smoke + edge-case suite for the cost_report_chart test probe.

Imports from ``tools.test_gap_cost_chart.probe`` so CLI and suite share one code
path (D-1). Asserts the *observed contract* (D-3): the renderer returns valid PNG
bytes for the known-good input and for every edge case it tolerates. Writes only
into pytest ``tmp_path``; touches no ``tokens-ace`` path.
"""

from tools.test_gap_cost_chart.probe import (
    PNG_SIGNATURE,
    ProbeError,
    assert_valid_png,
    is_valid_png,
    known_good_input,
    main,
    run_render,
    selfcheck,
)

import pytest


# --- smoke -----------------------------------------------------------------

def test_known_good_input_shape():
    series = known_good_input()
    assert isinstance(series, list) and len(series) >= 2
    assert all("label" in rec and "cost" in rec for rec in series)


def test_render_known_good_is_valid_png():
    data = run_render(known_good_input())
    assert is_valid_png(data)
    assert data[:8] == PNG_SIGNATURE


def test_render_returns_bytes():
    data = run_render(known_good_input())
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 64


# --- edge cases (D-3): empty / single / zero / negative / missing-key -------

@pytest.mark.parametrize(
    "series",
    [
        [],                                            # empty series
        [{"label": "solo", "cost": 7.0}],              # single data point
        [{"label": "free", "cost": 0}],                # zero cost
        [{"label": "credit", "cost": -3.25}],          # negative cost
        [{"label": "broken"}],                         # missing 'cost' key
        [{"cost": 1.0}, {"label": "x", "cost": 2.0}],  # missing 'label' key
        [{"label": "bad", "cost": "not-a-number"}],    # non-numeric cost
        [42, {"label": "y", "cost": 1.0}],             # non-dict record
    ],
)
def test_edge_cases_render_clean_valid_png(series):
    # Observed contract: the renderer tolerates these and emits valid PNG bytes.
    data = run_render(series)
    assert is_valid_png(data)
    assert data[:8] == PNG_SIGNATURE


# --- structural validity helpers -------------------------------------------

def test_assert_valid_png_rejects_non_bytes():
    with pytest.raises(ProbeError):
        assert_valid_png("/some/path.png")


def test_assert_valid_png_rejects_too_small():
    with pytest.raises(ProbeError):
        assert_valid_png(PNG_SIGNATURE)  # signature only, below the size floor


def test_assert_valid_png_rejects_bad_signature():
    with pytest.raises(ProbeError):
        assert_valid_png(b"\x00" * 128)  # right size, wrong signature


def test_is_valid_png_false_on_garbage():
    assert is_valid_png(b"not a png") is False
    assert is_valid_png(None) is False


# --- determinism -----------------------------------------------------------

def test_render_is_deterministic():
    first = run_render(known_good_input())
    second = run_render(known_good_input())
    assert first == second


def test_distinct_inputs_may_differ_but_stay_valid():
    a = run_render([{"label": "a", "cost": 1.0}])
    b = run_render([{"label": "b", "cost": 250.0}])
    assert is_valid_png(a) and is_valid_png(b)


# --- selfcheck / CLI (deploy health probe) ---------------------------------

def test_selfcheck_returns_zero():
    assert selfcheck() == 0


def test_main_selfcheck_returns_zero():
    assert main(["--selfcheck"]) == 0


def test_main_no_args_returns_nonzero():
    assert main([]) == 2


# --- read-only / isolation guard -------------------------------------------

def test_render_writes_nothing_outside_tmp(tmp_path):
    before = set(tmp_path.iterdir())
    run_render(known_good_input())
    after = set(tmp_path.iterdir())
    assert before == after  # render produces bytes in-memory, writes no files
