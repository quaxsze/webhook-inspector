import secrets


def generate_token() -> str:
    """Generate a URL-safe token with 128 bits of entropy."""
    return secrets.token_urlsafe(16)
