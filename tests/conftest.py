from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from company_analyzer.config import Settings
from company_analyzer.db.connection import DBConnection, split_sql_statements


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(raw_data_dir=tmp_path / "raw")


@pytest.fixture
def conn(settings: Settings) -> DBConnection:
    """Each test gets its own throwaway Postgres schema against the real
    Supabase project, created before and dropped after - full isolation from
    real data (a plain rolled-back transaction wouldn't be enough, since a
    test could still read pre-existing committed rows, e.g. a real 'NAVER'
    company, within its own transaction under READ COMMITTED)."""
    dsn = settings.require_db_url()
    schema_name = f"test_{uuid.uuid4().hex[:16]}"
    connection = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        with connection.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema_name}"')
            cur.execute(f'SET search_path TO "{schema_name}", public')
        connection.commit()

        schema_sql = settings.schema_path.read_text(encoding="utf-8")
        with connection.cursor() as cur:
            for statement in split_sql_statements(schema_sql):
                cur.execute(statement)
        connection.commit()

        yield connection
    finally:
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        connection.commit()
        connection.close()
