"""search_vector

Revision ID: 5058fb3e1c3e
Revises: 7f4cc8bfe09b
Create Date: 2026-05-13 18:59:06.648304

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5058fb3e1c3e"
down_revision: str | Sequence[str] | None = "7f4cc8bfe09b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tsvector generated column + GIN index for full-text search."""
    # Add tsvector generated column. jsonb_out is IMMUTABLE in Postgres 12+,
    # so headers::text is safe inside a STORED generated expression.
    op.execute(
        """
        ALTER TABLE requests ADD COLUMN search_vector tsvector
          GENERATED ALWAYS AS (
            to_tsvector('simple',
              coalesce(method, '') || ' ' ||
              coalesce(path, '') || ' ' ||
              coalesce(body_preview, '') || ' ' ||
              coalesce(headers::text, '')
            )
          ) STORED
        """
    )

    # GIN index, built concurrently to avoid blocking writes.
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS requests_search_idx "
            "ON requests USING GIN (search_vector)"
        )


def downgrade() -> None:
    """Drop GIN index + tsvector generated column."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS requests_search_idx")
    op.execute("ALTER TABLE requests DROP COLUMN IF EXISTS search_vector")
