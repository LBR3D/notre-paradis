"""ventes DVF

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dvf_sale",
        sa.Column("id_mutation", sa.String(30), primary_key=True),
        sa.Column("sold_on", sa.Date(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("commune_code", sa.String(5), nullable=False),
        sa.Column("surface", sa.Float()),
        sa.Column("land", sa.Float()),
        sa.Column("rooms", sa.Integer()),
        sa.Column("address", sa.Text()),
        sa.Column("geom", Geometry("POINT", srid=4326, spatial_index=False)),
    )
    op.create_index("ix_dvf_sale_sold_on", "dvf_sale", ["sold_on"])
    op.create_index("ix_dvf_sale_commune_code", "dvf_sale", ["commune_code"])
    op.execute("CREATE INDEX idx_dvf_sale_geom ON dvf_sale USING gist (geom)")


def downgrade() -> None:
    op.drop_table("dvf_sale")
