"""Typed domain exceptions raised during Endpoint validation."""


class EndpointValidationError(Exception):
    """Base class for endpoint validation failures."""


class InvalidResponseStatusError(EndpointValidationError):
    """response_status_code is outside [100, 599]."""


class InvalidResponseDelayError(EndpointValidationError):
    """response_delay_ms is outside [0, 30000]."""


class ResponseBodyTooLargeError(EndpointValidationError):
    """response_body exceeds 64 KiB."""


class ForbiddenResponseHeaderError(EndpointValidationError):
    """response_headers contains a header that must be controlled by the server."""
