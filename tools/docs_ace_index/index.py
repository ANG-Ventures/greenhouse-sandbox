"""docs.ace doc-portal index generator (v0.1).

Reads a hand-maintained TOML manifest of Ace's internal ``.ace`` pages and
renders a single self-contained dark-mode HTML index. Pure renderer: no
network, no liveness probing, no state outside its own directory.

Stdlib only (Python 3.11): tomllib, html, argparse, pathlib, sys, datetime.
"""

from __future__ import annotations

import html
import tomllib
from datetime import datetime, timezone
from pathlib import Path

# --- Schema / decisions -----------------------------------------------------

REQUIRED_FIELDS = ("name", "url")  # D-6: only name + url are required.

# D-2: declared (not probed) status values, rendered as colored pills.
STATUS_VALUES = ("live", "planned", "stale", "broken")
DEFAULT_STATUS = "planned"

# D-5: sort by status severity (broken/stale surface to top) then name.
STATUS_SEVERITY = {"broken": 0, "stale": 1, "planned": 2, "live": 3}

# Pill colors per status (inline CSS, no external assets).
STATUS_COLOR = {
    "broken": "#ff5c5c",
    "stale": "#e0a92e",
    "planned": "#7d8590",
    "live": "#3fb950",
}

PLACEHOLDER = "\u2014"  # em dash for missing optional fields.

DEFAULT_MANIFEST = Path(__file__).with_name("manifest.toml")
KNOWN_GOOD_FIXTURE = Path(__file__).with_name("fixtures") / "known_good.toml"


class ManifestError(ValueError):
    """Raised when the manifest is structurally invalid (hard error, D-6)."""


def load_manifest(path: Path) -> list[dict]:
    """Parse a TOML manifest and return its list of entry tables.

    Raises ManifestError if the file is missing the ``[[entry]]`` array or it
    is not a list of tables.
    """
    path = Path(path)
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("entry")
    if entries is None:
        raise ManifestError("manifest has no [[entry]] array")
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) for e in entries
    ):
        raise ManifestError("[[entry]] must be an array of tables")
    return entries


def validate(entries: list[dict]) -> list[dict]:
    """Validate + normalize entries.

    Hard error (ManifestError) if any entry is missing a required field, with
    the offending entry index (D-6). Optional fields are filled with the
    placeholder; status defaults to ``planned`` and is range-checked.
    """
    normalized: list[dict] = []
    for i, entry in enumerate(entries):
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ManifestError(
                    f"entry[{i}] missing required field {field!r}"
                )
        status = entry.get("status", DEFAULT_STATUS)
        if status not in STATUS_VALUES:
            raise ManifestError(
                f"entry[{i}] has invalid status {status!r}; "
                f"expected one of {STATUS_VALUES}"
            )
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(
            isinstance(t, str) for t in tags
        ):
            raise ManifestError(f"entry[{i}] 'tags' must be a list of strings")
        normalized.append(
            {
                "name": entry["name"],
                "url": entry["url"],
                "status": status,
                "type": entry.get("type"),
                "owner": entry.get("owner"),
                "generator": entry.get("generator"),
                "tags": tags,
            }
        )
    return normalized


def _sort_key(entry: dict) -> tuple[int, str]:
    sev = STATUS_SEVERITY.get(entry["status"], 99)
    return (sev, entry["name"].lower())


def _cell(value) -> str:
    """Escape a value for a table cell, or placeholder when empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return PLACEHOLDER
    return html.escape(str(value))


def _status_pill(status: str) -> str:
    safe = html.escape(status)
    color = STATUS_COLOR.get(status, "#7d8590")
    return (
        f'<span class="pill" style="background:{color}1a;'
        f'color:{color};border:1px solid {color}55">{safe}</span>'
    )


def _tag_chips(tags: list[str]) -> str:
    if not tags:
        return PLACEHOLDER
    return "".join(
        f'<span class="chip">{html.escape(t)}</span>' for t in tags
    )


def _url_link(url: str) -> str:
    safe = html.escape(url)
    return f'<a href="{safe}">{safe}</a>'


def render_html(entries: list[dict]) -> str:
    """Render validated entries into one self-contained dark-mode HTML string.

    Every manifest string is HTML-escaped before insertion. No external
    CSS/JS/font/image references.
    """
    rows = []
    for e in sorted(entries, key=_sort_key):
        rows.append(
            "<tr>"
            f'<td class="name">{_cell(e["name"])}</td>'
            f'<td class="url">{_url_link(e["url"])}</td>'
            f"<td>{_status_pill(e['status'])}</td>"
            f"<td>{_cell(e['type'])}</td>"
            f"<td>{_cell(e['owner'])}</td>"
            f"<td>{_cell(e['generator'])}</td>"
            f'<td class="tags">{_tag_chips(e["tags"])}</td>'
            "</tr>"
        )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    count = len(entries)
    body_rows = "\n".join(rows) if rows else (
        '<tr><td colspan="7" class="empty">No entries in manifest.</td></tr>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>docs.ace \u2014 index</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 2rem;
  background: #0d1117; color: #e6edf3;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; }}
.sub {{ color: #7d8590; margin: 0 0 1.5rem; font-size: .85rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{
  text-align: left; padding: .55rem .75rem;
  border-bottom: 1px solid #21262d; vertical-align: top;
}}
th {{ color: #7d8590; font-size: .72rem; text-transform: uppercase;
     letter-spacing: .04em; }}
tr:hover td {{ background: #161b22; }}
td.name {{ font-weight: 600; }}
a {{ color: #58a6ff; text-decoration: none; word-break: break-all; }}
a:hover {{ text-decoration: underline; }}
.pill {{ display: inline-block; padding: .1rem .5rem; border-radius: 999px;
        font-size: .72rem; font-weight: 600; }}
.chip {{ display: inline-block; padding: .08rem .45rem; margin: .1rem;
        border-radius: 4px; font-size: .7rem;
        background: #21262d; color: #c9d1d9; }}
.empty {{ color: #7d8590; text-align: center; font-style: italic; }}
</style>
</head>
<body>
<h1>docs.ace</h1>
<p class="sub">Front door for the .ace universe \u00b7 {count} entries \u00b7 generated {generated}</p>
<table>
<thead>
<tr><th>Name</th><th>URL</th><th>Status</th><th>Type</th><th>Owner</th><th>Generator</th><th>Tags</th></tr>
</thead>
<tbody>
{body_rows}
</tbody>
</table>
</body>
</html>
"""


def build(manifest: Path | None = None, out: Path | None = None) -> Path:
    """Read manifest, validate, render, write HTML. Return the output path."""
    manifest = Path(manifest) if manifest else DEFAULT_MANIFEST
    out = Path(out) if out else manifest.with_name("index.html")
    entries = validate(load_manifest(manifest))
    out.write_text(render_html(entries), encoding="utf-8")
    return out


def selfcheck() -> bool:
    """Deploy health probe: render the bundled known-good fixture.

    Returns True iff the fixture loads, validates, and produces a non-trivial
    self-contained HTML document. No files are written.
    """
    try:
        entries = validate(load_manifest(KNOWN_GOOD_FIXTURE))
    except (ManifestError, OSError, tomllib.TOMLDecodeError):
        return False
    if not entries:
        return False
    out = render_html(entries)
    if not out.startswith("<!doctype html>"):
        return False
    # Every fixture entry name must appear (escaped) in the rendered output.
    for e in entries:
        if html.escape(e["name"]) not in out:
            return False
    return True
