from __future__ import annotations

from company_analyzer.db.connection import DBConnection
from pathlib import Path

import frontmatter

from company_analyzer.db import repository as repo
from company_analyzer.models import Document

REQUIRED_FIELDS = ("title", "source_type")


class ManualDocumentError(ValueError):
    pass


def _load_one(conn: DBConnection, company_id: int, path: Path) -> tuple[Document, bool]:
    post = frontmatter.load(path)
    missing = [f for f in REQUIRED_FIELDS if not post.get(f)]
    if missing:
        raise ManualDocumentError(f"{path}: missing required front-matter field(s): {', '.join(missing)}")

    source_type = post["source_type"]
    title = post["title"]
    url = post.get("url")
    published_date = post.get("published_date")
    is_official = source_type != "news"
    body = post.content.strip()
    if not body:
        raise ManualDocumentError(f"{path}: document body is empty")

    return repo.upsert_document(
        conn,
        company_id=company_id,
        source_type=source_type,
        is_official=is_official,
        title=title,
        url=url,
        published_date=str(published_date) if published_date else None,
        external_id=f"manual:{path.stem}",
        raw_text=body,
        file_path=str(path),
        metadata={"manual_slug": path.stem},
    )


def ingest_manual_documents(conn: DBConnection, company_id: int, company_dir: Path) -> dict:
    """Scan company_dir/<source_type>/*.md and upsert each into `documents`.

    Returns a summary dict: {"ingested": int, "unchanged": int, "failed": [(path, error), ...]}.
    """
    ingested = 0
    unchanged = 0
    failed: list[tuple[str, str]] = []

    if not company_dir.exists():
        return {"ingested": 0, "unchanged": 0, "failed": []}

    for path in sorted(company_dir.rglob("*.md")):
        try:
            _document, changed = _load_one(conn, company_id, path)
        except (ManualDocumentError, OSError) as exc:
            failed.append((str(path), str(exc)))
            repo.log_ingestion(
                conn, source="manual", company_id=company_id, status="failed",
                detail=str(path), error_message=str(exc),
            )
            continue
        if changed:
            ingested += 1
        else:
            unchanged += 1
        repo.log_ingestion(
            conn, source="manual", company_id=company_id,
            status="success", detail=f"{path} (changed={changed})",
        )

    return {"ingested": ingested, "unchanged": unchanged, "failed": failed}
