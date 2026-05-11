from dataclasses import dataclass, field  # noqa: F401
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


@dataclass(slots=True)
class Endpoint:
    id: UUID
    token: str
    created_at: datetime
    expires_at: datetime
    request_count: int = 0

    @classmethod
    def create(cls, token: str, ttl_days: int) -> "Endpoint":
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            token=token,
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            request_count=0,
        )

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at
