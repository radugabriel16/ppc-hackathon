"""Region and network asset models."""
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPkMixin
from app.models.enums import AssetType


class Region(UUIDPkMixin, Base):
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    center = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    bounds: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    geometry = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)

    assets: Mapped[list["NetworkAsset"]] = relationship(back_populates="region")


class Subregion(UUIDPkMixin, Base):
    __tablename__ = "subregions"

    region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    geometry = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class NetworkAsset(UUIDPkMixin, Base):
    __tablename__ = "network_assets"
    __table_args__ = (
        CheckConstraint(
            "rated_capacity_kw IS NULL OR rated_capacity_kw > 0",
            name="ck_network_assets_rated_capacity_positive",
        ),
    )

    region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subregion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subregions.id", ondelete="SET NULL"), index=True,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type"), nullable=False
    )
    geometry = mapped_column(Geometry(srid=4326), nullable=False)
    rated_capacity_kw: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    region: Mapped["Region"] = relationship(back_populates="assets")
