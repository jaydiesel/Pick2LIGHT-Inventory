"""labels: label_template, default templates and the category foreign keys

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 16:00:00.000000
"""
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _text(
    value: str, x: float, y: float, w: float, h: float, size: float, **kw: Any
) -> dict[str, Any]:
    return {"type": "text", "value": value, "x": x, "y": y, "w": w, "h": h, "font_size": size, **kw}


def _code(symbology: str, value: str, x: float, y: float, size: float) -> dict[str, Any]:
    return {"type": "barcode", "symbology": symbology, "value": value, "x": x, "y": y, "size": size}


# (name, width_mm, height_mm, target, layout). Frozen copies: later edits to the app's
# defaults must not change what this migration inserted.
SEEDS = [
    (
        "Item 50×30", 50, 30, "item",
        [
            _code("qr", "{sku}", 2, 3, 24),
            _text("{name}", 28, 3, 20, 10, 11, bold=True, max_lines=2),
            _text("{sku}", 28, 14, 20, 4, 8),
            _text("{attrs_line}", 28, 19, 20, 9, 7, max_lines=3),
        ],
    ),
    (
        "Unit 30×15", 30, 15, "unit",
        [
            _code("datamatrix", "{unit_code}", 1.5, 1.5, 12),
            _text("{unit_code}", 15, 1.5, 14, 4.5, 9, bold=True),
            _text("{summary_line}", 15, 6.5, 14, 7, 6, max_lines=2),
        ],
    ),
    (
        "Cell wrap 40×30", 40, 30, "unit",
        [
            _code("datamatrix", "{unit_code}", 2, 2, 14),
            _text("{unit_code}", 18, 2, 20, 6, 12, bold=True),
            _text("{name}", 18, 9, 20, 7, 8, max_lines=2),
            _text("{summary_line}", 2, 18, 36, 10, 8, max_lines=3),
        ],
    ),
    (
        "Location 50×30", 50, 30, "location",
        [
            _code("qr", "{code}", 2, 3, 24),
            _text("{name}", 28, 3, 20, 10, 12, bold=True, max_lines=2),
            _text("{code}", 28, 14, 20, 4, 8),
            _text("{location.path}", 28, 19, 20, 9, 7, max_lines=3),
        ],
    ),
    (
        "Item 40×30", 40, 30, "item",
        [
            _code("qr", "{sku}", 2, 2, 16),
            _text("{sku}", 20, 2, 18, 5, 8, bold=True),
            _text("{name}", 2, 19, 36, 6, 10, bold=True),
            _text("{attrs_line}", 2, 25.5, 36, 4, 6),
        ],
    ),
]


def upgrade() -> None:
    template = op.create_table('label_template',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('width_mm', sa.Float(), nullable=False),
    sa.Column('height_mm', sa.Float(), nullable=False),
    sa.Column('dpi', sa.Integer(), server_default='203', nullable=False),
    sa.Column('target', sa.String(length=10), nullable=False),
    sa.Column('layout', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("target IN ('item', 'unit', 'location', 'command')", name=op.f('ck_label_template_target')),
    sa.CheckConstraint('width_mm > 0 AND height_mm > 0', name=op.f('ck_label_template_size')),
    sa.CheckConstraint('dpi > 0', name=op.f('ck_label_template_dpi')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_label_template'))
    )
    op.bulk_insert(
        template,
        [
            {"name": n, "width_mm": w, "height_mm": h, "target": t, "layout": layout}
            for n, w, h, t, layout in SEEDS
        ],
    )
    for column in ('default_label_template_id', 'default_unit_label_template_id'):
        # No templates existed before, so any stored id is dangling.
        op.execute(f'UPDATE category SET {column} = NULL')
        op.create_foreign_key(op.f(f'fk_category_{column}_label_template'), 'category', 'label_template', [column], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    for column in ('default_unit_label_template_id', 'default_label_template_id'):
        op.drop_constraint(op.f(f'fk_category_{column}_label_template'), 'category', type_='foreignkey')
    op.drop_table('label_template')
