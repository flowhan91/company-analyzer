from __future__ import annotations

from company_analyzer.db.connection import DBConnection
from datetime import date, timedelta

from company_analyzer.config import Settings
from company_analyzer.db import repository as repo
from company_analyzer.ingestion.dart_client import (
    DartApiError,
    DartFiling,
    fetch_filing_text,
    list_disclosures,
    resolve_corp_code,
)


# OpenDART report categories worth extracting business/product events from:
# A = periodic disclosure (annual/quarterly/semi-annual business reports),
# B = major matters report (capital changes, M&A, treasury stock, etc.).
# Deliberately excludes D (equity/ownership disclosure) and others - those
# are near-entirely routine officer/major-shareholder stock filings with no
# business content, and dwarf the substantive filings in raw count (a single
# ~6-month window for NAVER returned 100 filings unfiltered, 58 of them
# officer stock-ownership reports, vs. 8 across A+B).
DEFAULT_REPORT_CATEGORIES = ("A", "B")


def ingest_dart_filings(
    conn: DBConnection,
    settings: Settings,
    company_name: str,
    days: int = 365,
    report_categories: tuple[str, ...] | None = DEFAULT_REPORT_CATEGORIES,
) -> dict:
    """Resolve the company's DART corp code (cached on the companies row),
    list disclosures for the window, fetch+store each one not already ingested.

    report_categories defaults to periodic + major-matters reports only (see
    DEFAULT_REPORT_CATEGORIES) - pass None to fetch every disclosure type
    unfiltered, or a custom tuple of OpenDART pblntf_ty codes.
    """
    api_key = settings.require_opendart_key()
    company = repo.get_or_create_company(conn, company_name)

    corp_code = company.dart_corp_code
    if not corp_code:
        corp_code = resolve_corp_code(api_key, company_name)
        repo.set_dart_corp_code(conn, company.id, corp_code)

    today = date.today()
    date_from = (today - timedelta(days=days)).strftime("%Y%m%d")
    date_to = today.strftime("%Y%m%d")

    ingested, unchanged, failed = 0, 0, []
    categories = report_categories or (None,)
    filings_by_rcept: dict[str, DartFiling] = {}
    try:
        for category in categories:
            for filing in list_disclosures(api_key, corp_code, date_from, date_to, pblntf_ty=category):
                filings_by_rcept[filing.rcept_no] = filing
    except DartApiError as exc:
        repo.log_ingestion(conn, source="dart", company_id=company.id, status="failed", error_message=str(exc))
        return {"ingested": 0, "unchanged": 0, "failed": [("list_disclosures", str(exc))]}
    filings = list(filings_by_rcept.values())

    for filing in filings:
        try:
            text = fetch_filing_text(api_key, filing.rcept_no)
            published = f"{filing.rcept_date[:4]}-{filing.rcept_date[4:6]}-{filing.rcept_date[6:8]}"
            _document, changed = repo.upsert_document(
                conn, company_id=company.id, source_type="dart", is_official=True,
                title=filing.report_name, url=None, published_date=published,
                external_id=filing.rcept_no, raw_text=text,
                metadata={"rcept_no": filing.rcept_no},
            )
            if changed:
                ingested += 1
            else:
                unchanged += 1
            repo.log_ingestion(
                conn, source="dart", company_id=company.id, status="success",
                detail=f"{filing.rcept_no} (changed={changed})",
            )
        except (DartApiError, KeyError) as exc:
            failed.append((filing.rcept_no, str(exc)))
            repo.log_ingestion(
                conn, source="dart", company_id=company.id, status="failed",
                detail=filing.rcept_no, error_message=str(exc),
            )

    return {"ingested": ingested, "unchanged": unchanged, "failed": failed}
