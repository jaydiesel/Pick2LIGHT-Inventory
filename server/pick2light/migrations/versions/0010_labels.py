"""labels

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 05:07:13.317863
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEED = json.loads(
    """
[
    {
        "name": "Item 50×30",
        "width_mm": 50,
        "height_mm": 30,
        "dpi": 203,
        "target": "item",
        "layout": [
            {
                "type": "barcode",
                "symbology": "qr",
                "value": "{sku}",
                "x": 1,
                "y": 2,
                "size": 26
            },
            {
                "type": "text",
                "value": "{name}",
                "x": 29,
                "y": 2,
                "w": 20,
                "h": 12,
                "font_size": 10,
                "bold": true,
                "max_lines": 2,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{sku}",
                "x": 29,
                "y": 15,
                "w": 20,
                "h": 5,
                "font_size": 7,
                "bold": false,
                "max_lines": 1,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{label_line}",
                "x": 29,
                "y": 21,
                "w": 20,
                "h": 8,
                "font_size": 7,
                "bold": false,
                "max_lines": 2,
                "align": "left"
            }
        ]
    },
    {
        "name": "Item 40×30",
        "width_mm": 40,
        "height_mm": 30,
        "dpi": 203,
        "target": "item",
        "layout": [
            {
                "type": "barcode",
                "symbology": "qr",
                "value": "{sku}",
                "x": 1,
                "y": 1,
                "size": 20
            },
            {
                "type": "text",
                "value": "{name}",
                "x": 22,
                "y": 1,
                "w": 17,
                "h": 12,
                "font_size": 9,
                "bold": true,
                "max_lines": 2,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{sku}",
                "x": 1,
                "y": 22,
                "w": 38,
                "h": 4,
                "font_size": 7,
                "bold": false,
                "max_lines": 1,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{label_line}",
                "x": 1,
                "y": 26,
                "w": 38,
                "h": 4,
                "font_size": 6,
                "bold": false,
                "max_lines": 1,
                "align": "left"
            }
        ]
    },
    {
        "name": "Unit 30×15",
        "width_mm": 30,
        "height_mm": 15,
        "dpi": 203,
        "target": "unit",
        "layout": [
            {
                "type": "barcode",
                "symbology": "datamatrix",
                "value": "{unit_code}",
                "x": 1,
                "y": 1.5,
                "size": 12
            },
            {
                "type": "text",
                "value": "{unit_code}",
                "x": 14,
                "y": 1,
                "w": 15,
                "h": 5,
                "font_size": 9,
                "bold": true,
                "max_lines": 1,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{summary_line}",
                "x": 14,
                "y": 7,
                "w": 15,
                "h": 7,
                "font_size": 6,
                "bold": false,
                "max_lines": 2,
                "align": "left"
            }
        ]
    },
    {
        "name": "Cell wrap 40×30",
        "width_mm": 40,
        "height_mm": 30,
        "dpi": 203,
        "target": "unit",
        "layout": [
            {
                "type": "barcode",
                "symbology": "datamatrix",
                "value": "{unit_code}",
                "x": 1,
                "y": 1,
                "size": 14
            },
            {
                "type": "text",
                "value": "{unit_code}",
                "x": 17,
                "y": 1,
                "w": 22,
                "h": 6,
                "font_size": 11,
                "bold": true,
                "max_lines": 1,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{item.name}",
                "x": 17,
                "y": 8,
                "w": 22,
                "h": 8,
                "font_size": 7,
                "bold": false,
                "max_lines": 2,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{summary_line}",
                "x": 1,
                "y": 17,
                "w": 38,
                "h": 12,
                "font_size": 7,
                "bold": false,
                "max_lines": 3,
                "align": "left"
            }
        ]
    },
    {
        "name": "Location 50×30",
        "width_mm": 50,
        "height_mm": 30,
        "dpi": 203,
        "target": "location",
        "layout": [
            {
                "type": "barcode",
                "symbology": "qr",
                "value": "{code}",
                "x": 1,
                "y": 2,
                "size": 26
            },
            {
                "type": "text",
                "value": "{name}",
                "x": 29,
                "y": 2,
                "w": 20,
                "h": 12,
                "font_size": 11,
                "bold": true,
                "max_lines": 2,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{code}",
                "x": 29,
                "y": 15,
                "w": 20,
                "h": 5,
                "font_size": 7,
                "bold": false,
                "max_lines": 1,
                "align": "left"
            },
            {
                "type": "text",
                "value": "{path}",
                "x": 29,
                "y": 21,
                "w": 20,
                "h": 8,
                "font_size": 6,
                "bold": false,
                "max_lines": 2,
                "align": "left"
            }
        ]
    }
]
"""
)


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "label_template",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("width_mm", sa.Float(), nullable=False),
        sa.Column("height_mm", sa.Float(), nullable=False),
        sa.Column("dpi", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "target IN ('item','unit','location','command')", name=op.f("ck_label_template_target")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_label_template")),
        sa.UniqueConstraint("name", name=op.f("uq_label_template_name")),
    )
    op.create_foreign_key(
        op.f("fk_category_default_unit_label_template_id_label_template"),
        "category",
        "label_template",
        ["default_unit_label_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_category_default_label_template_id_label_template"),
        "category",
        "label_template",
        ["default_label_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # ### end Alembic commands ###
    table = sa.table(
        "label_template",
        sa.column("name", sa.String),
        sa.column("width_mm", sa.Float),
        sa.column("height_mm", sa.Float),
        sa.column("dpi", sa.Integer),
        sa.column("target", sa.String),
        sa.column("layout", postgresql.JSONB),
    )
    op.bulk_insert(table, SEED)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(
        op.f("fk_category_default_label_template_id_label_template"), "category", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_category_default_unit_label_template_id_label_template"), "category", type_="foreignkey"
    )
    op.drop_table("label_template")
    # ### end Alembic commands ###
