from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID


class Notifier(ABC):
    """Consumer-side port for new-request notifications.

    The producer side is handled by RequestRepository.save() which emits the
    notification transactionally (NOTIFY in the same transaction as the INSERT).
    """

    @abstractmethod
    def subscribe(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        """Yields request_id values for each new request on the endpoint."""
