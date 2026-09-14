from __future__ import annotations

import io
from company_analyzer.db.connection import DBConnection
import zipfile

import responses

from company_analyzer.config import Settings
from company_analyzer.db import repository as repo
from company_analyzer.ingestion.dart_ingest import ingest_dart_filings


def _zip_bytes(filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


CORP_CODE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list>
    <corp_code>00266961</corp_code>
    <corp_name>NAVER</corp_name>
    <stock_code>035420</stock_code>
    <modify_date>20250101</modify_date>
  </list>
</result>
"""


@responses.activate
def test_ingest_dart_filings_resolves_corp_code_and_stores_documents(conn: DBConnection):
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/corpCode.xml",
        body=_zip_bytes("CORPCODE.xml", CORP_CODE_XML), status=200,
        content_type="application/x-zip-compressed",
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/list.json",
        json={
            "status": "000", "message": "ok",
            "list": [
                {"rcept_no": "20250601000001", "report_nm": "분기보고서", "rcept_dt": "20250601", "corp_name": "NAVER"},
            ],
        },
        status=200,
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/document.xml",
        body=_zip_bytes("20250601000001.html", b"<html><body><h1>1. Overview</h1><p>NAVER grew revenue.</p></body></html>"),
        status=200, content_type="application/x-zip-compressed",
    )

    settings = Settings(opendart_api_key="test-key")
    summary = ingest_dart_filings(conn, settings, "NAVER", days=365)

    assert summary["ingested"] == 1
    assert summary["failed"] == []

    company = repo.get_company_by_name(conn, "NAVER")
    assert company.dart_corp_code == "00266961"

    docs = repo.list_documents(conn, company.id, source_type="dart")
    assert len(docs) == 1
    assert "NAVER grew revenue" in docs[0].raw_text
    assert docs[0].published_date == "2025-06-01"


@responses.activate
def test_ingest_dart_filings_reruns_without_duplicating(conn: DBConnection):
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/corpCode.xml",
        body=_zip_bytes("CORPCODE.xml", CORP_CODE_XML), status=200,
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/list.json",
        json={"status": "000", "message": "ok", "list": [
            {"rcept_no": "20250601000001", "report_nm": "분기보고서", "rcept_dt": "20250601", "corp_name": "NAVER"},
        ]},
        status=200,
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/document.xml",
        body=_zip_bytes("f.html", b"<html><body>Same content.</body></html>"),
        status=200,
    )

    settings = Settings(opendart_api_key="test-key")
    ingest_dart_filings(conn, settings, "NAVER", days=365)

    company = repo.get_company_by_name(conn, "NAVER")
    # Second run: corp code already cached, so no second corpCode.xml call is
    # strictly required, but list.json/document.xml will be hit again.
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/list.json",
        json={"status": "000", "message": "ok", "list": [
            {"rcept_no": "20250601000001", "report_nm": "분기보고서", "rcept_dt": "20250601", "corp_name": "NAVER"},
        ]},
        status=200,
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/document.xml",
        body=_zip_bytes("f.html", b"<html><body>Same content.</body></html>"),
        status=200,
    )
    summary2 = ingest_dart_filings(conn, settings, "NAVER", days=365)
    assert summary2["ingested"] == 0
    assert summary2["unchanged"] == 1

    docs = repo.list_documents(conn, company.id, source_type="dart")
    assert len(docs) == 1


@responses.activate
def test_ingest_dart_filings_defaults_to_periodic_and_major_matters_categories(conn: DBConnection):
    """Regression test: an unfiltered real ingest for NAVER returned 100
    filings, 58 of them routine officer stock-ownership reports with zero
    business content. Defaults must query only categories A (periodic) and
    B (major matters), excluding noise categories like D (equity/ownership)."""
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/corpCode.xml",
        body=_zip_bytes("CORPCODE.xml", CORP_CODE_XML), status=200,
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/list.json",
        json={"status": "000", "message": "ok", "list": [
            {"rcept_no": "A0001", "report_nm": "분기보고서", "rcept_dt": "20250601", "corp_name": "NAVER"},
        ]},
        status=200,
        match=[responses.matchers.query_param_matcher({"pblntf_ty": "A"}, strict_match=False)],
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/list.json",
        json={"status": "000", "message": "ok", "list": [
            {"rcept_no": "B0001", "report_nm": "주요사항보고서(유상증자결정)", "rcept_dt": "20250602", "corp_name": "NAVER"},
        ]},
        status=200,
        match=[responses.matchers.query_param_matcher({"pblntf_ty": "B"}, strict_match=False)],
    )
    responses.add(
        responses.GET, "https://opendart.fss.or.kr/api/document.xml",
        body=_zip_bytes("f.html", b"<html><body>Report content.</body></html>"),
        status=200,
    )

    settings = Settings(opendart_api_key="test-key")
    summary = ingest_dart_filings(conn, settings, "NAVER", days=151)

    assert summary["ingested"] == 2
    # A category-D-only request was never registered above - `responses`
    # would raise ConnectionError for any unmatched request, which the
    # try/except in ingest_dart_filings would swallow into `failed` - so a
    # clean `failed == []` also guards against widening the default
    # categories back to "everything".
    assert summary["failed"] == []
    company = repo.get_company_by_name(conn, "NAVER")
    docs = repo.list_documents(conn, company.id, source_type="dart")
    assert {d.external_id for d in docs} == {"A0001", "B0001"}


def test_ingest_dart_filings_requires_api_key(conn: DBConnection):
    settings = Settings(opendart_api_key=None)
    try:
        ingest_dart_filings(conn, settings, "NAVER")
        assert False, "expected ConfigError"
    except Exception as exc:
        assert "OPENDART_API_KEY" in str(exc)
