import re

from webhook_inspector.domain.services.token_generator import generate_token


def test_token_is_url_safe_string():
    token = generate_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_token_has_at_least_128_bits_of_entropy():
    # 16 bytes urlsafe → 22 chars sans padding
    token = generate_token()
    assert len(token) >= 22


def test_tokens_are_unique_across_calls():
    tokens = {generate_token() for _ in range(1000)}
    assert len(tokens) == 1000
