"""User-supplied slug validation. Auto-generated tokens bypass this."""

import re

from webhook_inspector.domain.exceptions import InvalidSlugError, ReservedSlugError

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")

RESERVED_SLUGS: frozenset[str] = frozenset(
    [
        "api",
        "h",
        "health",
        "healthz",
        "stream",
        "static",
        "admin",
        "app",
        "hook",
        "www",
        "assets",
        "docs",
        "stripe",
        "github",
        "slack",
        "shopify",
        "twilio",
        "zapier",
        "discord",
    ]
)


def validate_slug(slug: str) -> None:
    """Raise InvalidSlugError or ReservedSlugError. Returns None on success."""
    if slug in RESERVED_SLUGS:
        raise ReservedSlugError(f"slug '{slug}' is reserved")
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError(
            "slug must be 3-32 chars, lowercase letters / digits / hyphens, "
            "no leading or trailing hyphen"
        )
