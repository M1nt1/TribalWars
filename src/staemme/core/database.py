"""SQLAlchemy database models and session management."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Float, Integer, String, Text, Boolean, func, ForeignKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class VillageRecord(Base):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # in-game village ID
    name: Mapped[str] = mapped_column(String(100), default="")
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    wood: Mapped[int] = mapped_column(Integer, default=0)
    stone: Mapped[int] = mapped_column(Integer, default=0)
    iron: Mapped[int] = mapped_column(Integer, default=0)
    storage: Mapped[int] = mapped_column(Integer, default=0)
    population: Mapped[int] = mapped_column(Integer, default=0)
    max_population: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    buildings: Mapped[list[BuildingRecord]] = relationship(back_populates="village")
    troops: Mapped[list[TroopRecord]] = relationship(back_populates="village")


class BuildingRecord(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    name: Mapped[str] = mapped_column(String(50))
    level: Mapped[int] = mapped_column(Integer, default=0)

    village: Mapped[VillageRecord] = relationship(back_populates="buildings")


class TroopRecord(Base):
    __tablename__ = "troops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    unit: Mapped[str] = mapped_column(String(30))
    count_own: Mapped[int] = mapped_column(Integer, default=0)
    count_available: Mapped[int] = mapped_column(Integer, default=0)

    village: Mapped[VillageRecord] = relationship(back_populates="troops")


class FarmTargetRecord(Base):
    __tablename__ = "farm_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # target village ID
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    is_barbarian: Mapped[bool] = mapped_column(Boolean, default=True)
    wall_level: Mapped[int] = mapped_column(Integer, default=0)
    last_loot_wood: Mapped[int] = mapped_column(Integer, default=0)
    last_loot_stone: Mapped[int] = mapped_column(Integer, default=0)
    last_loot_iron: Mapped[int] = mapped_column(Integer, default=0)
    has_troops: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_attacked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attack_count: Mapped[int] = mapped_column(Integer, default=0)


class ActionLogRecord(Base):
    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    village_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)


class Database:
    """Async database wrapper."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession)

    async def init(self) -> None:
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_session(self) -> AsyncSession:
        return self.session_factory()

    async def close(self) -> None:
        await self.engine.dispose()
