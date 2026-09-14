from __future__ import annotations

import click

from company_analyzer.config import get_settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import get_connection, init_db
from company_analyzer.review import actions, queue


@click.group("review")
def review_group() -> None:
    """Work the human-review queue for uncertain LLM decisions."""


@review_group.command("summary")
@click.option("--company", required=True)
def review_summary_cmd(company: str) -> None:
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        company_id = repo.get_or_create_company(conn, company).id
        summary = queue.review_summary(conn, company_id)
    for key, value in summary.items():
        click.echo(f"{key}: {value}")


@review_group.command("list-evidence")
@click.option("--company", required=True)
def list_evidence_cmd(company: str) -> None:
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        company_id = repo.get_or_create_company(conn, company).id
        for item in queue.pending_evidence(conn, company_id):
            span, event = item["evidence"], item["event"]
            click.echo(f"[evidence:{span.id}] score={span.match_score:.2f} event={event.event_type!r}")
            click.echo(f"  quote:   {span.raw_quote}")
            click.echo(f"  matched: {span.matched_text}")


@review_group.command("approve-evidence")
@click.argument("evidence_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def approve_evidence_cmd(evidence_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        actions.approve_evidence(conn, evidence_id, human_id)
    click.echo(f"evidence {evidence_id} approved")


@review_group.command("reject-evidence")
@click.argument("evidence_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def reject_evidence_cmd(evidence_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        actions.reject_evidence(conn, evidence_id, human_id)
    click.echo(f"evidence {evidence_id} rejected")


@review_group.command("list-duplicates")
def list_duplicates_cmd() -> None:
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        for item in queue.pending_event_relationships(conn, relationship_type="same_event"):
            rel, a, b = item["relationship"], item["event_a"], item["event_b"]
            click.echo(f"[relationship:{rel.id}] confidence={rel.confidence:.2f}")
            click.echo(f"  A: {a.entity or a.subject} - {a.raw_quote}")
            click.echo(f"  B: {b.entity or b.subject} - {b.raw_quote}")
            click.echo(f"  rationale: {rel.rationale}")


@review_group.command("approve-duplicate")
@click.argument("relationship_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def approve_duplicate_cmd(relationship_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        canonical = actions.approve_event_relationship(conn, relationship_id, human_id)
    click.echo(f"relationship {relationship_id} approved -> canonical_event {canonical.id}")


@review_group.command("reject-duplicate")
@click.argument("relationship_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def reject_duplicate_cmd(relationship_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        actions.reject_event_relationship(conn, relationship_id, human_id)
    click.echo(f"relationship {relationship_id} rejected")


@review_group.command("list-threads")
def list_thread_relationships_cmd() -> None:
    settings = get_settings()
    init_db(settings)
    with get_connection(settings) as conn:
        for item in queue.pending_canonical_relationships(conn, relationship_type="related_distinct"):
            rel, a, b = item["relationship"], item["canonical_event_a"], item["canonical_event_b"]
            click.echo(f"[relationship:{rel.id}] confidence={rel.confidence:.2f}")
            click.echo(f"  A: {a.title} ({a.canonical_date})")
            click.echo(f"  B: {b.title} ({b.canonical_date})")
            click.echo(f"  rationale: {rel.rationale}")


@review_group.command("approve-thread")
@click.argument("relationship_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def approve_thread_cmd(relationship_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        thread = actions.approve_canonical_relationship(conn, relationship_id, human_id)
    click.echo(f"relationship {relationship_id} approved -> thread {thread.id}")


@review_group.command("reject-thread")
@click.argument("relationship_id", type=int)
@click.option("--as", "human_id", default="cli-user")
def reject_thread_cmd(relationship_id: int, human_id: str) -> None:
    settings = get_settings()
    with get_connection(settings) as conn:
        actions.reject_canonical_relationship(conn, relationship_id, human_id)
    click.echo(f"relationship {relationship_id} rejected")
