"""Suite for the docs.ace doc-portal index generator (PRD §3 invariants).

Imports from ``tools.docs_ace_index`` so the CLI and the suite share one code
path. Asserts the observed contract: validated TOML in, a single self-contained
dark-mode HTML doc out, manifest content escaped as data, a deterministic
--selfcheck probe. Writes only into pytest ``tmp_path``.
"""

import ast
import pathlib

import pytest

from tools.docs_ace_index import (
    ManifestError,
    build,
    load_manifest,
    render_html,
    selfcheck,
    validate,
)
from tools.docs_ace_index import index as idx
from tools.docs_ace_index.__main__ import main


GOOD_MANIFEST = """
[[entry]]
name = "alpha.ace"
url = "https://alpha.ace/"
status = "live"
type = "portal"
owner = "Apollo"
generator = "nightly"
tags = ["a", "b"]

[[entry]]
name = "zeta.ace"
url = "https://zeta.ace/"
status = "broken"
"""


def write_manifest(tmp_path, text):
    p = tmp_path / "manifest.toml"
    p.write_text(text, encoding="utf-8")
    return p


# --- load + validate (D-6) --------------------------------------------------

def test_load_manifest_returns_entries(tmp_path):
    entries = load_manifest(write_manifest(tmp_path, GOOD_MANIFEST))
    assert [e["name"] for e in entries] == ["alpha.ace", "zeta.ace"]


def test_load_manifest_missing_file_errors(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nope.toml")


def test_load_manifest_no_entry_array_errors(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(write_manifest(tmp_path, 'title = "x"\n'))


def test_validate_defaults_status_and_optionals(tmp_path):
    p = write_manifest(tmp_path, '[[entry]]\nname = "x.ace"\nurl = "u"\n')
    e = validate(load_manifest(p))[0]
    assert e["status"] == "planned"
    assert e["type"] is None
    assert e["tags"] == []


def test_validate_missing_required_is_hard_error_with_index(tmp_path):
    p = write_manifest(
        tmp_path,
        '[[entry]]\nname = "ok.ace"\nurl = "u"\n[[entry]]\nname = "no-url"\n',
    )
    with pytest.raises(ManifestError) as exc:
        validate(load_manifest(p))
    assert "entry[1]" in str(exc.value) and "url" in str(exc.value)


def test_validate_rejects_unknown_status(tmp_path):
    p = write_manifest(
        tmp_path, '[[entry]]\nname = "x"\nurl = "u"\nstatus = "bogus"\n'
    )
    with pytest.raises(ManifestError):
        validate(load_manifest(p))


# --- render (D-3, D-5, D-6) -------------------------------------------------

def test_render_is_single_html_document():
    out = render_html(validate([{"name": "x.ace", "url": "u"}]))
    assert out.startswith("<!doctype html>")
    assert out.count("<!doctype html>") == 1
    assert "</html>" in out and "<style>" in out


def test_render_sorts_broken_then_stale_then_live():
    out = render_html(validate([
        {"name": "live-1.ace", "url": "u", "status": "live"},
        {"name": "broken-1.ace", "url": "u", "status": "broken"},
        {"name": "stale-1.ace", "url": "u", "status": "stale"},
    ]))
    assert out.index("broken-1.ace") < out.index("stale-1.ace") < out.index("live-1.ace")


def test_render_placeholder_and_pills():
    out = render_html(validate([
        {"name": "a.ace", "url": "u", "status": "broken"},
    ]))
    assert "\u2014" in out          # em-dash placeholder for missing optionals
    assert 'class="pill"' in out and ">broken<" in out


# --- invariant: HTML escaping (trust boundary) ------------------------------

def test_html_escaping_blocks_injection():
    out = render_html(validate([{
        "name": "<script>alert(1)</script>",
        "url": '"><img onerror=alert(1)>',
        "tags": ["<b>x</b>"],
    }]))
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<img onerror=" not in out
    assert "&lt;img onerror=alert(1)&gt;" in out
    assert "<b>x</b>" not in out and "&lt;b&gt;x&lt;/b&gt;" in out


# --- invariant: single self-contained HTML file -----------------------------

def test_output_self_contained_no_external_assets():
    out = render_html(validate([
        {"name": "x.ace", "url": "https://content-url.ace/page"},
    ]))
    assert "<link" not in out      # no external stylesheet
    assert "<script" not in out    # zero JS in v0.1
    assert "<img" not in out
    assert 'src="http' not in out
    assert "@import" not in out


# --- invariant: no state outside own files / no network ---------------------

def test_no_external_writes(tmp_path):
    p = write_manifest(tmp_path, GOOD_MANIFEST)
    before = {f.name for f in tmp_path.iterdir()}
    out = build(manifest=p, out=tmp_path / "index.html")
    new = {f.name for f in tmp_path.iterdir()} - before
    assert new == {"index.html"}
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_build_default_out_beside_manifest(tmp_path):
    out = build(manifest=write_manifest(tmp_path, GOOD_MANIFEST))
    assert out == tmp_path / "index.html" and out.is_file()


def test_imports_are_stdlib_only_and_no_network():
    allowed = {
        "__future__", "tomllib", "html", "argparse", "pathlib",
        "sys", "datetime",
    }
    pkg_dir = pathlib.Path(idx.__file__).parent
    for py in pkg_dir.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] in allowed, f"{py.name}:{a.name}"
            elif isinstance(node, ast.ImportFrom) and not node.level:
                assert (node.module or "").split(".")[0] in allowed, py.name


# --- invariant: --selfcheck health probe ------------------------------------

def test_selfcheck_passes_on_known_good():
    assert selfcheck() is True
    assert main(["--selfcheck"]) == 0


def test_selfcheck_detects_corruption(tmp_path, monkeypatch):
    corrupt = tmp_path / "corrupt.toml"
    corrupt.write_text("this is { not valid toml ][", encoding="utf-8")
    monkeypatch.setattr(idx, "KNOWN_GOOD_FIXTURE", corrupt)
    assert selfcheck() is False
    assert main(["--selfcheck"]) == 1


def test_selfcheck_detects_missing_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(idx, "KNOWN_GOOD_FIXTURE", tmp_path / "gone.toml")
    assert selfcheck() is False


# --- CLI build path ---------------------------------------------------------

def test_cli_build_writes_output(tmp_path):
    p = write_manifest(tmp_path, GOOD_MANIFEST)
    out_path = tmp_path / "out.html"
    assert main(["build", "--manifest", str(p), "--out", str(out_path)]) == 0
    assert out_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_build_bad_manifest_nonzero(tmp_path):
    p = write_manifest(tmp_path, '[[entry]]\nname = "x"\n')  # missing url
    assert main(["build", "--manifest", str(p), "--out", str(tmp_path / "o.html")]) == 2
