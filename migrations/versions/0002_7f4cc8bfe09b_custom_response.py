"""custom response

Revision ID: 7f4cc8bfe09b
Revises: 19068e2673bf
Create Date: 2026-05-13 11:04:35.629659

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7f4cc8bfe09b"
down_revision: str | Sequence[str] | None = "19068e2673bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add custom response config to endpoints."""
    op.add_column(
        "endpoints",
        sa.Column(
            "response_status_code",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("200"),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_body",
            sa.Text(),
            nullable=False,
            server_default=sa.text(r"""'{"ok"\:true}'"""),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_delay_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Drop custom response columns."""
    op.drop_column("endpoints", "response_delay_ms")
    op.drop_column("endpoints", "response_headers")
    op.drop_column("endpoints", "response_body")
    op.drop_column("endpoints", "response_status_code")
