import json
import logging

from webhook_inspector.observability.logging import configure_logging


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO", service_name="test-svc")
    logger = logging.getLogger("test_logger")
    logger.info("hello world", extra={"user_id": 42})

    captured = capsys.readouterr().out
    line = captured.strip().split("\n")[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello world"
    assert payload["service.name"] == "test-svc"
    assert payload["user_id"] == 42
