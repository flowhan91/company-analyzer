from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request

from company_analyzer.config import ConfigError, get_settings
from company_analyzer.db.connection import DBConnection
from company_analyzer.jd_matching.matcher import EmptyJDError, NoEmbeddedEvidenceError, match_jd
from company_analyzer.jd_matching.parser import parse_and_store_jd
from company_analyzer.llm.factory import get_llm_provider
from company_analyzer.web.deps import list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates

router = APIRouter()


@router.get("/jd-match")
def jd_match_form(
    request: Request,
    company: str | None = Query(default=None),
    conn: DBConnection = Depends(get_db),
):
    company_row = resolve_company(conn, company)
    return templates.TemplateResponse(
        request,
        "jd_match.html",
        {
            "company_name": company_row.name,
            "companies": list_company_names(conn),
            "active_tab": "jd_match",
            "jd_text": "",
            "jd": None,
            "candidates": None,
            "error": None,
        },
    )


@router.post("/jd-match")
def jd_match_submit(
    request: Request,
    company: str = Form(...),
    jd_text: str = Form(...),
    conn: DBConnection = Depends(get_db),
):
    company_row = resolve_company(conn, company)
    context = {
        "company_name": company_row.name,
        "companies": list_company_names(conn),
        "active_tab": "jd_match",
        "jd_text": jd_text,
        "jd": None,
        "candidates": None,
        "error": None,
    }

    try:
        provider = get_llm_provider(get_settings())
    except ConfigError as exc:
        context["error"] = str(exc)
        return templates.TemplateResponse(request, "jd_match.html", context)

    if not jd_text or not jd_text.strip():
        context["error"] = "채용공고 내용을 붙여넣어 주세요."
        return templates.TemplateResponse(request, "jd_match.html", context)

    jd = parse_and_store_jd(conn, company_row.id, jd_text, provider)
    context["jd"] = jd

    try:
        context["candidates"] = match_jd(conn, company_row.id, jd, provider, top_n=3)
    except EmptyJDError:
        context["error"] = "채용공고에서 구체적인 업무 내용을 추출하지 못했습니다. 더 상세한 내용을 붙여넣어 주세요."
    except NoEmbeddedEvidenceError:
        context["error"] = (
            "아직 이 기업의 근거 자료가 임베딩되지 않았습니다. "
            "`cana embed-evidence --company " + company_row.name + "`를 먼저 실행하세요."
        )

    return templates.TemplateResponse(request, "jd_match.html", context)
