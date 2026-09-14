from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DISCLOSURE_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"


class DartApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class DartFiling:
    rcept_no: str
    report_name: str
    rcept_date: str  # YYYYMMDD from DART
    corp_name: str


def fetch_corp_code_map(api_key: str, session: requests.Session | None = None) -> dict[str, str]:
    """Download OpenDART's bulk corp-code list once. Returns {corp_name: corp_code}.

    Callers should cache this (e.g. to a local file) rather than re-fetching
    per run - it's a multi-MB zipped XML covering every listed company.
    """
    session = session or requests
    resp = session.get(CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=30)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for entry in root.findall(".//list"):
        name = entry.findtext("corp_name")
        code = entry.findtext("corp_code")
        if name and code:
            mapping[name.strip()] = code.strip()
    return mapping


def resolve_corp_code(api_key: str, corp_name: str, session: requests.Session | None = None) -> str:
    mapping = fetch_corp_code_map(api_key, session=session)
    if corp_name in mapping:
        return mapping[corp_name]
    raise DartApiError(f"No DART corp_code found for company name '{corp_name}'.")


def list_disclosures(
    api_key: str,
    corp_code: str,
    date_from: str,
    date_to: str,
    pblntf_ty: str | None = None,
    session: requests.Session | None = None,
) -> list[DartFiling]:
    """date_from/date_to as YYYYMMDD strings.

    pblntf_ty filters by OpenDART's report category (A=periodic disclosure,
    B=major matters report, C=securities issuance, D=equity/ownership
    disclosure, E-J=other administrative categories). Omit for everything
    unfiltered - see ingest_dart_filings for why callers should usually pass
    one.
    """
    session = session or requests
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": date_from,
        "end_de": date_to,
        "page_count": 100,
    }
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty
    resp = session.get(DISCLOSURE_LIST_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    status = payload.get("status")
    if status not in ("000", "013"):  # 013 = no data found, not an error
        raise DartApiError(f"OpenDART list.json error {status}: {payload.get('message')}")
    filings = []
    for item in payload.get("list", []):
        filings.append(
            DartFiling(
                rcept_no=item["rcept_no"], report_name=item["report_nm"],
                rcept_date=item["rcept_dt"], corp_name=item["corp_name"],
            )
        )
    return filings


def fetch_filing_text(api_key: str, rcept_no: str, session: requests.Session | None = None) -> str:
    """Fetch a filing's document zip and return its plain text, headings preserved
    reasonably well for section_chunker to find them."""
    session = session or requests
    resp = session.get(DOCUMENT_URL, params={"crtfc_key": api_key, "rcept_no": rcept_no}, timeout=60)
    resp.raise_for_status()
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            texts = []
            for name in zf.namelist():
                raw = zf.read(name)
                # DART's document.xml endpoint despite its name returns real
                # XML-formatted filing bodies (confirmed against a live
                # filing) - html.parser on XML content works but warns; use
                # the matching parser.
                parser = "xml" if name.lower().endswith(".xml") else "html.parser"
                soup = BeautifulSoup(raw, parser)
                texts.append(soup.get_text("\n", strip=True))
            return "\n\n".join(texts)
    except zipfile.BadZipFile as exc:
        raise DartApiError(f"OpenDART document.xml did not return a valid zip for rcept_no={rcept_no}") from exc
