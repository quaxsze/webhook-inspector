import pytest

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.exceptions import (
    ForbiddenResponseHeaderError,
    InvalidResponseDelayError,
    InvalidResponseStatusError,
    ResponseBodyTooLargeError,
)


def test_create_endpoint_with_defaults_keeps_v1_behavior():
    e = Endpoint.create(token="t", ttl_days=7)
    assert e.response_status_code == 200
    assert e.response_body == '{"ok":true}'
    assert e.response_headers == {}
    assert e.response_delay_ms == 0


def test_create_endpoint_accepts_custom_response_config():
    e = Endpoint.create(
        token="t",
        ttl_days=7,
        response_status_code=201,
        response_body='{"created":true}',
        response_headers={"Content-Type": "application/json"},
        response_delay_ms=500,
    )
    assert e.response_status_code == 201
    assert e.response_body == '{"created":true}'
    assert e.response_headers == {"Content-Type": "application/json"}
    assert e.response_delay_ms == 500


@pytest.mark.parametrize("status", [99, 600, -1, 0, 1000])
def test_create_endpoint_rejects_invalid_status_code(status):
    with pytest.raises(InvalidResponseStatusError):
        Endpoint.create(token="t", ttl_days=7, response_status_code=status)


@pytest.mark.parametrize("delay", [-1, 30001, 60000])
def test_create_endpoint_rejects_out_of_range_delay(delay):
    with pytest.raises(InvalidResponseDelayError):
        Endpoint.create(token="t", ttl_days=7, response_delay_ms=delay)


def test_create_endpoint_rejects_oversized_response_body():
    body = "x" * 65_537  # 64 KiB + 1
    with pytest.raises(ResponseBodyTooLargeError):
        Endpoint.create(token="t", ttl_days=7, response_body=body)


@pytest.mark.parametrize(
    "header_name",
    ["Content-Length", "content-length", "Transfer-Encoding", "Connection", "Host", "Date"],
)
def test_create_endpoint_rejects_forbidden_response_headers(header_name):
    with pytest.raises(ForbiddenResponseHeaderError):
        Endpoint.create(token="t", ttl_days=7, response_headers={header_name: "value"})
