from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from webhook_inspector.domain.entities.endpoint import Endpoint


def test_create_endpoint_assigns_uuid_and_token():
    endpoint = Endpoint.create(token="abc123", ttl_days=7)

    assert isinstance(endpoint.id, UUID)
    assert endpoint.token == "abc123"
    assert endpoint.request_count == 0


def test_create_endpoint_sets_expiry_from_ttl():
    before = datetime.now(UTC)
    endpoint = Endpoint.create(token="abc123", ttl_days=7)
    after = datetime.now(UTC)

    expected_min = before + timedelta(days=7)
    expected_max = after + timedelta(days=7)
    assert expected_min <= endpoint.expires_at <= expected_max


def test_endpoint_is_expired_when_past_expiry():
    past = datetime.now(UTC) - timedelta(seconds=1)
    endpoint = Endpoint(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        token="abc",
        created_at=past - timedelta(days=7),
        expires_at=past,
        request_count=0,
    )
    assert endpoint.is_expired() is True


def test_endpoint_is_not_expired_when_future():
    future = datetime.now(UTC) + timedelta(days=1)
    endpoint = Endpoint(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        token="abc",
        created_at=datetime.now(UTC),
        expires_at=future,
        request_count=0,
    )
    assert endpoint.is_expired() is False


def test_create_endpoint_rejects_negative_ttl():
    with pytest.raises(ValueError, match="ttl_days must be positive"):
        Endpoint.create(token="abc", ttl_days=0)
