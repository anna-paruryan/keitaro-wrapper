"""Миграции применяются с нуля, совпадают с моделями и откатываются."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app import models  # noqa: F401
from app.db import Base, make_engine

ROOT = Path(__file__).resolve().parents[1]


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_matches_models_and_downgrade_works(tmp_path):
    url = f"sqlite:///{tmp_path / 'nested' / 'test.db'}"
    cfg = alembic_cfg(url)

    command.upgrade(cfg, "head")
    engine = make_engine(url)
    assert {"campaigns", "offer_changes", "alembic_version"} <= set(inspect(engine).get_table_names())

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"миграция и модели разошлись: {diff}"

    command.downgrade(cfg, "base")
    assert {"campaigns", "offer_changes"}.isdisjoint(inspect(make_engine(url)).get_table_names())
