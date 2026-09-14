from __future__ import annotations

import click

from company_analyzer.chunking.dispatch import chunk_document
from company_analyzer.clustering.build_canonical_events import cluster_new_events
from company_analyzer.config import ConfigError, get_settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import get_connection, init_db
from company_analyzer.evidence.validator import validate_pending_events
from company_analyzer.extraction.extractor import extract_pending_chunks
from company_analyzer.ingestion.manual_loader import ingest_manual_documents
from company_analyzer.llm.factory import get_llm_provider
from company_analyzer.threading.build_threads import rebuild_threads
from company_analyzer.timeline.build_timeline import build_timeline
from company_analyzer.translation.translate_titles import (
    translate_canonical_event_titles,
    translate_thread_titles,
)


def _company_id(conn, company: str) -> int:
    return repo.get_or_create_company(conn, company).id


@click.command("chunk")
@click.option("--company", required=True)
def chunk_cmd(company: str) -> None:
    """Chunk every un-chunked document for this company."""
    settings = get_settings()
    init_db(settings)
    count = 0
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        for document in repo.list_unchunked_documents(conn, company_id):
            drafts = chunk_document(document.source_type, document.title, document.raw_text)
            repo.replace_chunks(conn, document.id, drafts)
            count += len(drafts)
    click.echo(f"chunks created: {count}")


@click.command("extract")
@click.option("--company", required=True)
def extract_cmd(company: str) -> None:
    """Run event+evidence extraction on every un-extracted chunk."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        total = extract_pending_chunks(conn, company_id, provider)
    click.echo(f"events extracted: {total} (provider={provider.name})")


@click.command("validate-evidence")
@click.option("--company", required=True)
def validate_evidence_cmd(company: str) -> None:
    """Fuzzy-match every un-validated event's quote back to its source chunk."""
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        counts = validate_pending_events(conn, company_id)
    click.echo(f"auto_valid={counts.get('auto_valid', 0)} pending={counts.get('pending', 0)} rejected={counts.get('rejected', 0)}")


@click.command("cluster-events")
@click.option("--company", required=True)
def cluster_events_cmd(company: str) -> None:
    """Hybrid duplicate detection: merge same-event candidates into canonical events."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        counts = cluster_new_events(conn, company_id, provider)
    click.echo(
        f"new_canonical={counts['new_canonical']} merged={counts['merged']} "
        f"flagged_for_review={counts['flagged_for_review']} "
        f"deferred_news_event={counts['deferred_news_event']}"
    )


@click.command("build-threads")
@click.option("--company", required=True)
def build_threads_cmd(company: str) -> None:
    """Hybrid threading: connect canonical events into long-running initiatives."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        counts = rebuild_threads(conn, company_id, provider)
    click.echo(
        f"appended_to_thread={counts['appended_to_thread']} "
        f"created_thread={counts['created_thread']} standalone={counts['standalone']} "
        f"already_threaded={counts['already_threaded']}"
    )


@click.command("show-timeline")
@click.option("--company", required=True)
@click.option("--from", "date_from", default=None)
@click.option("--to", "date_to", default=None)
def show_timeline_cmd(company: str, date_from: str | None, date_to: str | None) -> None:
    """Print the chronological canonical-event timeline."""
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        timeline = build_timeline(conn, company_id, date_from=date_from, date_to=date_to)
    for ce in timeline:
        click.echo(f"[{ce.canonical_date or '????'}] ({ce.review_status}) {ce.title}")


@click.command("show-threads")
@click.option("--company", required=True)
def show_threads_cmd(company: str) -> None:
    """Print every thread with its member canonical events in order."""
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        for thread in repo.list_threads(conn, company_id):
            click.echo(f"Thread: {thread.title} ({thread.review_status})")
            for te in repo.list_thread_events(conn, thread.id):
                ce = repo.get_canonical_event(conn, te.canonical_event_id)
                click.echo(f"  [{te.sequence_index}] {te.stage or '?':<10} {ce.canonical_date or '????'}  {ce.title}")


@click.command("translate-titles")
@click.option("--company", required=True)
def translate_titles_cmd(company: str) -> None:
    """Backfill Korean display titles for canonical events/threads whose
    title isn't Korean yet (new extractions already come out Korean)."""
    settings = get_settings()
    init_db(settings)
    try:
        provider = get_llm_provider(settings)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    with get_connection(settings) as conn:
        company_id = _company_id(conn, company)
        events_translated = translate_canonical_event_titles(conn, company_id, provider)
        threads_translated = translate_thread_titles(conn, company_id, provider)
    click.echo(f"canonical_events translated={events_translated} threads translated={threads_translated}")


@click.command("run-all")
@click.option("--company", required=True)
@click.pass_context
def run_all_cmd(ctx: click.Context, company: str) -> None:
    """Chain everything except the two live-API ingests: ingest-manual, chunk,
    extract, validate-evidence, cluster-events, build-threads."""
    from company_analyzer.cli.commands.ingest import ingest_manual_cmd

    for cmd in (
        ingest_manual_cmd, chunk_cmd, extract_cmd, validate_evidence_cmd,
        cluster_events_cmd, build_threads_cmd,
    ):
        click.echo(f"--- {cmd.name} ---")
        ctx.invoke(cmd, company=company)
