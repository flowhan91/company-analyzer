from __future__ import annotations

import click

from company_analyzer.config import ConfigError, get_settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import get_connection, init_db
from company_analyzer.jd_matching.embed_evidence import backfill_evidence_embeddings
from company_analyzer.jd_matching.matcher import EmptyJDError, NoEmbeddedEvidenceError, match_jd
from company_analyzer.jd_matching.parser import parse_and_store_jd
from company_analyzer.llm.factory import get_llm_provider


@click.command("embed-evidence")
@click.option("--company", required=True)
def embed_evidence_cmd(company: str) -> None:
    """Backfill embeddings for every valid evidence span that doesn't have
    one yet - needed once before `match-jd` can rank real evidence."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_row = repo.get_or_create_company(conn, company)
        count = backfill_evidence_embeddings(conn, company_row.id, provider)
    click.echo(f"embedded={count}")


@click.command("match-jd")
@click.option("--company", required=True)
@click.option("--text", required=True, help="Pasted job description text.")
@click.option("--top", "top_n", default=3, show_default=True)
def match_jd_cmd(company: str, text: str, top_n: int) -> None:
    """Parse a pasted JD and rank this company's threads/events by relevance."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_row = repo.get_or_create_company(conn, company)
        jd = parse_and_store_jd(conn, company_row.id, text, provider)
        click.echo(f"role={jd.role} domain={jd.domain} tasks={len(jd.tasks)}")
        try:
            candidates = match_jd(conn, company_row.id, jd, provider, top_n=top_n)
        except (EmptyJDError, NoEmbeddedEvidenceError) as exc:
            raise click.ClickException(str(exc)) from exc

    for rank, candidate in enumerate(candidates, start=1):
        click.echo(f"\n#{rank} [{candidate.kind}] {candidate.title} (score={candidate.score:.3f})")
        for match in candidate.matches:
            click.echo(f"    JD task: {match.task}")
            click.echo(f"    Evidence: {match.evidence_text}")
