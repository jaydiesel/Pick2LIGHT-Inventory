"""trash: ON DELETE rules that let the purge hard-delete rows

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03 14:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, referred table, ON DELETE rule): history rows keep a null reference,
# bookkeeping rows (stock, purchase sources) go with their owner.
RULES = [
    ('stock_movement', 'item_id', 'item', 'SET NULL'),
    ('stock_movement', 'unit_id', 'unit', 'SET NULL'),
    ('stock_movement', 'from_location_id', 'location', 'SET NULL'),
    ('stock_movement', 'to_location_id', 'location', 'SET NULL'),
    ('item', 'default_location_id', 'location', 'SET NULL'),
    ('unit', 'location_id', 'location', 'SET NULL'),
    ('stock', 'item_id', 'item', 'CASCADE'),
    ('stock', 'location_id', 'location', 'CASCADE'),
    ('purchase_source', 'item_id', 'item', 'CASCADE'),
]


def _recreate(ondelete: dict[tuple[str, str], str | None]) -> None:
    for table, column, ref, _ in RULES:
        name = op.f(f'fk_{table}_{column}_{ref}')
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, ref, [column], ['id'], ondelete=ondelete[(table, column)])


def upgrade() -> None:
    _recreate({(t, c): rule for t, c, _, rule in RULES})
    op.alter_column('stock_movement', 'item_id', existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    # Movements of purged items cannot be given an item back; drop them before re-tightening.
    op.execute('DELETE FROM stock_movement WHERE item_id IS NULL')
    op.alter_column('stock_movement', 'item_id', existing_type=sa.BigInteger(), nullable=False)
    _recreate({(t, c): None for t, c, _, _ in RULES})
