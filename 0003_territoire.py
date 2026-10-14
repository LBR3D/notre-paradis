"""données du territoire : routes, voies ferrées, aérodromes, installations classées

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE terr_road (
            id SERIAL PRIMARY KEY, cleabs VARCHAR(40) UNIQUE, nature VARCHAR(60), importance VARCHAR(2),
            lanes INTEGER, geom geometry(LineString, 4326))""")
    op.execute("CREATE INDEX idx_terr_road_geom ON terr_road USING gist (geom)")
    op.execute("""
        CREATE TABLE terr_rail (
            id SERIAL PRIMARY KEY, cleabs VARCHAR(40) UNIQUE, nature VARCHAR(60), geom geometry(LineString, 4326))""")
    op.execute("CREATE INDEX idx_terr_rail_geom ON terr_rail USING gist (geom)")
    op.execute("""
        CREATE TABLE terr_airfield (
            id SERIAL PRIMARY KEY, cleabs VARCHAR(40) UNIQUE, name VARCHAR(200), nature VARCHAR(60), geom geometry(Geometry, 4326))""")
    op.execute("CREATE INDEX idx_terr_airfield_geom ON terr_airfield USING gist (geom)")
    op.execute("""
        CREATE TABLE icpe_site (
            code VARCHAR(30) PRIMARY KEY, name VARCHAR(300), commune VARCHAR(100), regime VARCHAR(40), activity VARCHAR(80),
            kinds TEXT[] NOT NULL DEFAULT '{}', rubriques TEXT[] NOT NULL DEFAULT '{}', geom geometry(Point, 4326))""")
    op.execute("CREATE INDEX idx_icpe_site_geom ON icpe_site USING gist (geom)")


def downgrade() -> None:
    for t in ("icpe_site", "terr_airfield", "terr_rail", "terr_road"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
