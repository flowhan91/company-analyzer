from __future__ import annotations

from company_analyzer.db.connection import DBConnection
from pathlib import Path

from company_analyzer.db import repository as repo
from company_analyzer.ingestion.manual_loader import ManualDocumentError, ingest_manual_documents

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "naver"


def test_ingest_manual_documents_from_fixtures(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    summary = ingest_manual_documents(conn, company.id, FIXTURES_DIR)

    assert summary["ingested"] == 3
    assert summary["unchanged"] == 0
    assert summary["failed"] == []

    docs = repo.list_documents(conn, company.id)
    assert len(docs) == 3
    source_types = {d.source_type for d in docs}
    assert source_types == {"press_release", "tech_blog", "ir"}
    press = next(d for d in docs if d.source_type == "press_release")
    assert press.is_official is True
    assert press.title == "NAVER Launches AI-Powered Search Expansion"
    assert "AI-powered search service" in press.raw_text


def test_ingest_manual_documents_is_idempotent(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    ingest_manual_documents(conn, company.id, FIXTURES_DIR)
    summary2 = ingest_manual_documents(conn, company.id, FIXTURES_DIR)
    assert summary2["ingested"] == 0
    assert summary2["unchanged"] == 3


def test_ingest_manual_documents_reports_missing_frontmatter(tmp_path, conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    bad_dir = tmp_path / "bad_company" / "press_release"
    bad_dir.mkdir(parents=True)
    (bad_dir / "broken.md").write_text("---\ntitle: Missing source type\n---\nBody text.", encoding="utf-8")

    summary = ingest_manual_documents(conn, company.id, tmp_path / "bad_company")
    assert summary["ingested"] == 0
    assert len(summary["failed"]) == 1
    assert "source_type" in summary["failed"][0][1]
