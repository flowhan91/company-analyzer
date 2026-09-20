from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request

from company_analyzer.config import ConfigError, get_settings
from company_analyzer.db.connection import DBConnection
from company_analyzer.jd_matching.matcher import EmptyJDError, NoEmbeddedEvidenceError, match_jd
from company_analyzer.jd_matching.parser import parse_and_store_jd
from company_analyzer.llm.factory import get_llm_provider
from company_analyzer.web.deps import build_timeline_rows, list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates

router = APIRouter()

# Curated JDs covering the domains that actually show up in the NAVER
# timeline (AI/advertising, cloud infra, commerce, ESG) so the one-click
# presets return real, non-empty matches instead of a generic sample.
SAMPLE_JDS: list[dict[str, str]] = [
    {
        "id": "ai-ads",
        "label": "AI 서비스 기획자 (광고·커머스)",
        "text": (
            "[AI 서비스 기획자 - 광고/커머스]\n"
            "AI 기술을 활용해 광고 자동화 및 타겟팅 최적화 서비스를 기획합니다. "
            "피드형 광고, 검색 광고, 쇼핑 연동 광고 등 AI 기반 개인화 광고 상품의 "
            "기획부터 출시까지 리드하며, 광고주의 캠페인 성과와 사용자 만족도를 "
            "동시에 높이는 것을 목표로 합니다. 이커머스 트래픽 데이터를 활용한 "
            "추천/타겟팅 로직 기획 경험을 우대합니다."
        ),
    },
    {
        "id": "cloud-infra",
        "label": "클라우드·AI 인프라 엔지니어",
        "text": (
            "[클라우드/AI 인프라 엔지니어]\n"
            "대규모 AI 모델 학습·서빙을 위한 GPU 데이터센터 인프라를 설계·운영합니다. "
            "자체 데이터센터 및 클라우드 플랫폼 환경에서 GPU 클러스터 증설, "
            "전력/냉각 효율화, 재생에너지 기반 그린 데이터센터 운영 경험을 우대하며, "
            "글로벌 하드웨어 파트너와의 협력을 통한 AI 팩토리 구축 경험이 있으면 좋습니다."
        ),
    },
    {
        "id": "commerce-pm",
        "label": "이커머스 커머스 PM",
        "text": (
            "[이커머스 커머스 PM]\n"
            "소상공인 대상 온라인 쇼핑몰 구축 플랫폼과 라이브 커머스, C2C 리셀 "
            "플랫폼 등 커머스 신사업을 기획·운영합니다. 셀러 온보딩, 물류/풀필먼트 "
            "제휴, 브랜드 D2C 채널 확장 경험을 우대하며, 데이터 기반으로 커머스 "
            "지표(거래액, 셀러 성장)를 개선해본 경험이 있는 분을 찾습니다."
        ),
    },
    {
        "id": "esg-hr",
        "label": "ESG·지속가능경영 담당자",
        "text": (
            "[ESG/지속가능경영 담당자]\n"
            "탄소중립 로드맵 수립, RE100/EV100 등 글로벌 환경 이니셔티브 대응, "
            "ESG 채권 발행 및 대외 ESG 평가(MSCI, KCGS 등) 대응 업무를 담당합니다. "
            "데이터센터 등 사업장의 재생에너지 전환(PPA 계약 등) 프로젝트 경험과 "
            "인권경영/컴플라이언스 체계 구축 경험을 우대합니다."
        ),
    },
]


def _run_match(conn: DBConnection, company_row, jd_text: str | None, top_n: int = 10) -> dict:
    context: dict = {"jd_text": jd_text or "", "jd": None, "candidates": None, "error": None}

    try:
        provider = get_llm_provider(get_settings())
    except ConfigError as exc:
        context["error"] = str(exc)
        return context

    if not jd_text or not jd_text.strip():
        context["error"] = "채용공고 내용을 선택하거나 붙여넣어 주세요."
        return context

    jd = parse_and_store_jd(conn, company_row.id, jd_text, provider)
    context["jd"] = jd

    try:
        context["candidates"] = match_jd(conn, company_row.id, jd, provider, top_n=top_n)
    except EmptyJDError:
        context["error"] = "채용공고에서 구체적인 업무 내용을 추출하지 못했습니다. 더 상세한 내용을 붙여넣어 주세요."
    except NoEmbeddedEvidenceError:
        context["error"] = (
            "아직 이 기업의 근거 자료가 임베딩되지 않았습니다. "
            "`cana embed-evidence --company " + company_row.name + "`를 먼저 실행하세요."
        )

    return context


def _related_ids_and_scores(context: dict) -> tuple[set[int] | None, dict[int, float]]:
    """Flatten match candidates (threads and standalone events alike) down to
    the individual canonical-event ids they're backed by, so the timeline can
    highlight the actual event cards rather than just listing candidates."""
    if context.get("jd") is None:
        return None, {}

    related_ids: set[int] = set()
    score_by_id: dict[int, float] = {}
    for candidate in context.get("candidates") or []:
        for m in candidate.matches:
            related_ids.add(m.canonical_event_id)
            if m.canonical_event_id not in score_by_id or m.score > score_by_id[m.canonical_event_id]:
                score_by_id[m.canonical_event_id] = m.score
    return related_ids, score_by_id


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
    context = _run_match(conn, company_row, jd_text)
    context.update(
        {
            "company_name": company_row.name,
            "companies": list_company_names(conn),
            "active_tab": "jd_match",
        }
    )
    return templates.TemplateResponse(request, "jd_match.html", context)


@router.post("/jd-match/panel")
def jd_match_panel(
    request: Request,
    company: str = Form(...),
    preset_id: str | None = Form(default=None),
    jd_text: str | None = Form(default=None),
    domain: str | None = Form(default=None),
    official_only: str | None = Form(default=None),
    conn: DBConnection = Depends(get_db),
):
    """HTMX endpoint backing the timeline sidebar. Returns the sidebar body
    (buttons + results) as the primary swap target, plus two out-of-band
    fragments in the same response: the main timeline list re-rendered with
    matching event cards highlighted, and the "관련 이벤트만 보기" toggle
    made visible - so one click updates both the sidebar and the timeline
    without a full page reload."""
    company_row = resolve_company(conn, company)

    text = jd_text
    if preset_id:
        preset = next((p for p in SAMPLE_JDS if p["id"] == preset_id), None)
        text = preset["text"] if preset else jd_text

    context = _run_match(conn, company_row, text)
    context["active_preset"] = preset_id
    context["presets"] = SAMPLE_JDS
    context["company_name"] = company_row.name
    context["selected_domain"] = domain or ""
    context["official_only"] = bool(official_only)

    related_ids, score_by_id = _related_ids_and_scores(context)
    context["related_ids"] = related_ids
    context["score_by_id"] = score_by_id

    rows, _domains = build_timeline_rows(conn, company_row.id, domain=domain or None, official_only=bool(official_only))
    context["rows"] = rows

    return templates.TemplateResponse(request, "jd_panel_oob.html", context)
