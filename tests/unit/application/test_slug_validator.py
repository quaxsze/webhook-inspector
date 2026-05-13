import pytest

from webhook_inspector.application.services.slug_validator import validate_slug
from webhook_inspector.domain.exceptions import InvalidSlugError, ReservedSlugError


@pytest.mark.parametrize("slug", ["foo", "my-stripe-test", "a1b", "abc-123-def", "a" * 32])
def test_validate_slug_accepts_valid(slug):
    validate_slug(slug)  # must not raise


@pytest.mark.parametrize(
    "slug",
    [
        "ab",  # too short (< 3)
        "a" * 33,  # too long (> 32)
        "-foo",  # leading hyphen
        "foo-",  # trailing hyphen
        "Foo",  # uppercase
        "foo_bar",  # underscore
        "foo.bar",  # dot
        "fôo",  # non-ASCII
        "",  # empty
    ],
)
def test_validate_slug_rejects_invalid_format(slug):
    with pytest.raises(InvalidSlugError):
        validate_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "api",
        "h",
        "health",
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
    ],
)
def test_validate_slug_rejects_reserved(slug):
    with pytest.raises(ReservedSlugError):
        validate_slug(slug)
