import logging
from dataclasses import dataclass

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.notifier import Notifier
from webhook_inspector.domain.ports.request_repository import RequestRepository

logger = logging.getLogger(__name__)


class EndpointNotFoundError(Exception):
    pass


@dataclass
class CaptureRequest:
    endpoint_repo: EndpointRepository
    request_repo: RequestRepository
    blob_storage: BlobStorage
    notifier: Notifier
    inline_threshold: int

    async def execute(
        self,
        token: str,
        method: str,
        path: str,
        query_string: str | None,
        headers: dict[str, str],
        body: bytes,
        source_ip: str,
    ) -> CapturedRequest:
        endpoint = await self.endpoint_repo.find_by_token(token)
        if endpoint is None:
            raise EndpointNotFoundError(token)

        captured = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method=method.upper(),
            path=path,
            query_string=query_string,
            headers=headers,
            body=body,
            source_ip=source_ip,
            inline_threshold_bytes=self.inline_threshold,
        )

        if captured.blob_key is not None:
            try:
                await self.blob_storage.put(captured.blob_key, body)
            except Exception:
                logger.exception("blob_storage_put_failed", extra={"key": captured.blob_key})
                # Downgrade: drop blob reference; keep metadata
                captured = CapturedRequest(
                    id=captured.id,
                    endpoint_id=captured.endpoint_id,
                    method=captured.method,
                    path=captured.path,
                    query_string=captured.query_string,
                    headers=captured.headers,
                    body_preview=None,
                    body_size=captured.body_size,
                    blob_key=None,
                    source_ip=captured.source_ip,
                    received_at=captured.received_at,
                )

        await self.request_repo.save(captured)
        await self.endpoint_repo.increment_request_count(endpoint.id)
        await self.notifier.publish_new_request(endpoint.id, captured.id)

        return captured
