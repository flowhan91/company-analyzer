from __future__ import annotations

from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from company_analyzer.config import get_settings
from company_analyzer.db.connection import DBConnection, get_connection, init_db
from company_analyzer.web.labels import (
    format_date,
    match_method_label,
    review_status_label,
    source_type_label,
    stage_label,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["review_status_label"] = review_status_label
templates.env.filters["stage_label"] = stage_label
templates.env.filters["source_type_label"] = source_type_label
templates.env.filters["match_method_label"] = match_method_label
templates.env.filters["format_date"] = format_date


def get_db() -> Iterator[DBConnection]:
    settings = get_settings()
    with get_connection(settings) as conn:
        yield conn


def create_app() -> FastAPI:
    settings = get_settings()
    init_db(settings)

    application = FastAPI(title="Company Analyzer - Explorer")

    from company_analyzer.web.routers import documents, jd_match, review, threads, timeline

    application.include_router(timeline.router)
    application.include_router(threads.router)
    application.include_router(review.router)
    application.include_router(documents.router)
    application.include_router(jd_match.router)

    return application


app = create_app()
