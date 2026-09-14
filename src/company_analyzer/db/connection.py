from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from company_analyzer.config import Settings, get_settings

# init_db() runs on every CLI command, including its ALTER TABLE statements,
# which briefly need a table-level lock. Running the extended DART ingestion
# and other commands (e.g. translate-titles) side by side made that lock
# occasionally contend with the pipeline's own concurrent writes long enough
# to hit Supabase's statement timeout - a short retry absorbs that instead of
# failing an otherwise-fine command over a transient lock wait.
INIT_DB_RETRIES = 6
INIT_DB_RETRY_DELAY_SECONDS = 10.0

# Alias so the rest of the codebase can type-hint against the DB layer
# without importing psycopg directly - keeps a future driver swap contained.
DBConnection = psycopg.Connection


def _connect(dsn: str) -> DBConnection:
    # A real run through Supabase's session pooler hung for 90+ minutes with
    # zero CPU progress after the pooler silently dropped the connection -
    # the client just blocked forever waiting on a dead socket instead of
    # erroring. TCP keepalives make a dead connection surface as an error
    # within ~50s instead of hanging indefinitely; connect_timeout bounds the
    # initial handshake too.
    return psycopg.connect(
        dsn,
        row_factory=dict_row,
        autocommit=False,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=20,
        keepalives_interval=10,
        keepalives_count=3,
    )


def _column_exists(conn: DBConnection, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()
    return row is not None


def init_db(settings: Settings | None = None) -> None:
    """Create the schema if it doesn't already exist. Safe to call repeatedly."""
    settings = settings or get_settings()
    dsn = settings.require_db_url()
    schema_sql = settings.schema_path.read_text(encoding="utf-8")
    statements = split_sql_statements(schema_sql)

    for attempt in range(1, INIT_DB_RETRIES + 1):
        conn = _connect(dsn)
        try:
            with conn.cursor() as cur:
                for statement in statements:
                    # An ALTER TABLE ADD COLUMN needs an ACCESS EXCLUSIVE lock
                    # even when "IF NOT EXISTS" makes it a no-op - on every
                    # CLI command's init_db() call, that briefly blocks (and
                    # gets blocked by) any concurrent reader/writer of that
                    # table. Skipping the statement entirely once the column
                    # is already there (the common case after the first run)
                    # avoids taking that lock at all instead of just
                    # retrying through the contention.
                    if statement.upper().startswith("ALTER TABLE EVIDENCE_SPANS") and _column_exists(
                        conn, "evidence_spans", "embedding_json"
                    ):
                        continue
                    cur.execute(statement)
            conn.commit()
            return
        except psycopg.errors.QueryCanceled:
            conn.rollback()
            if attempt == INIT_DB_RETRIES:
                raise
            time.sleep(INIT_DB_RETRY_DELAY_SECONDS)
        finally:
            conn.close()


def split_sql_statements(schema_sql: str) -> list[str]:
    """Split a DDL script on top-level semicolons, ignoring `--` line comments
    first (schema.sql's header comments contain literal ';' characters, e.g.
    "separate tables; event_relationships is..." - splitting before stripping
    comments would cut a comment in half and send the remainder as SQL).
    Safe here because this schema has no dollar-quoted function/trigger
    bodies and no string literals containing '--'."""
    lines = []
    for line in schema_sql.splitlines():
        comment_idx = line.find("--")
        lines.append(line if comment_idx == -1 else line[:comment_idx])
    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


@contextmanager
def get_connection(settings: Settings | None = None) -> Iterator[DBConnection]:
    settings = settings or get_settings()
    dsn = settings.require_db_url()
    conn = _connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
