"""docs.ace doc-portal index generator package."""

from .index import (
    ManifestError,
    build,
    load_manifest,
    render_html,
    selfcheck,
    validate,
)

__all__ = [
    "ManifestError",
    "build",
    "load_manifest",
    "render_html",
    "selfcheck",
    "validate",
]
