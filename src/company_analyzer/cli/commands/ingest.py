from __future__ import annotations

from pathlib import Path

import click

from company_analyzer.config import ConfigError, get_settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import get_connection, init_db
from company_analyzer.ingestion.dart_ingest import ingest_dart_filings
from company_analyzer.ingestion.manual_loader import ingest_manual_documents
from company_analyzer.ingestion.news_ingest import NoCanonicalEventsError, ingest_news


@click.command("ingest-manual")
@click.option("--company", required=True, help="Company name, e.g. NAVER")
@click.option("--path", "path_", type=click.Path(path_type=Path), default=None,
              help="Directory to scan (default: <raw_data_dir>/<company lowercased>)")
def ingest_manual_cmd(company: str, path_: Path | None) -> None:
    """Scan a directory of front-matter documents and load them."""
    settings = get_settings()
    init_db(settings)
    company_dir = path_ or (settings.raw_data_dir / company.lower())
    with get_connection(settings) as conn:
        c = repo.get_or_create_company(conn, company)
        summary = ingest_manual_documents(conn, c.id, company_dir)
    click.echo(f"ingested={summary['ingested']} unchanged={summary['unchanged']} failed={len(summary['failed'])}")
    for path, error in summary["failed"]:
        click.echo(f"  FAILED {path}: {error}", err=True)


@click.command("ingest-dart")
@click.option("--company", required=True)
@click.option("--days", default=365, show_default=True)
def ingest_dart_cmd(company: str, days: int) -> None:
    """Fetch DART filings for the last N days."""
    settings = get_settings()
    init_db(settings)
    try:
        with get_connection(settings) as conn:
            summary = ingest_dart_filings(conn, settings, company, days=days)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"ingested={summary['ingested']} unchanged={summary['unchanged']} failed={len(summary['failed'])}")
    for item, error in summary["failed"]:
        click.echo(f"  FAILED {item}: {error}", err=True)


@click.command("ingest-news")
@click.option("--company", required=True)
@click.option("--max-results", default=100, show_default=True)
def ingest_news_cmd(company: str, max_results: int) -> None:
    """Fetch news for entities already established from official sources.

    Queries "<company> <entity>" per distinct entity in canonical_events -
    not a blind company-name search. Run official ingestion + cluster-events
    first, or this has nothing to search for yet.
    """
    settings = get_settings()
    init_db(settings)
    try:
        with get_connection(settings) as conn:
            summary = ingest_news(conn, settings, company, max_results=max_results)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    except NoCanonicalEventsError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"queries={summary['queries']}")
    click.echo(f"ingested={summary['ingested']} unchanged={summary['unchanged']} failed={len(summary['failed'])}")
    for item, error in summary["failed"]:
        click.echo(f"  FAILED {item}: {error}", err=True)
