from tools.greenpath_proof import normalize, selfcheck, main


def test_normalize_collapses_whitespace():
    assert normalize("  a   b \n c ") == "a b c"


def test_normalize_idempotent():
    once = normalize("  x   y ")
    assert normalize(once) == once


def test_selfcheck_green():
    assert selfcheck() == 0


def test_main_selfcheck_returns_zero():
    assert main(["--selfcheck"]) == 0
