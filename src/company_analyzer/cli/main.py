from __future__ import annotations

import click

from company_analyzer.cli.commands.ingest import ingest_dart_cmd, ingest_manual_cmd, ingest_news_cmd
from company_analyzer.cli.commands.jd import embed_evidence_cmd, match_jd_cmd
from company_analyzer.cli.commands.pipeline import (
    build_threads_cmd,
    chunk_cmd,
    cluster_events_cmd,
    extract_cmd,
    run_all_cmd,
    show_threads_cmd,
    show_timeline_cmd,
    translate_titles_cmd,
    validate_evidence_cmd,
)
from company_analyzer.cli.commands.review_cmds import review_group
from company_analyzer.config import get_settings
from company_analyzer.db.connection import init_db


@click.group()
def cli() -> None:
    """cana - JD-aware company intelligence: build a company timeline & threads."""


@cli.command("init-db")
def init_db_cmd() -> None:
    """Create the schema in the Supabase Postgres database if it doesn't already exist."""
    settings = get_settings()
    init_db(settings)
    click.echo("database schema ready")


@cli.command("serve")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000)
def serve_cmd(host: str, port: int) -> None:
    """Launch the web explorer (timeline, threads, review queue)."""
    import uvicorn

    uvicorn.run("company_analyzer.web.main:app", host=host, port=port, reload=False)


cli.add_command(ingest_manual_cmd)
cli.add_command(ingest_dart_cmd)
cli.add_command(ingest_news_cmd)
cli.add_command(chunk_cmd)
cli.add_command(extract_cmd)
cli.add_command(validate_evidence_cmd)
cli.add_command(cluster_events_cmd)
cli.add_command(build_threads_cmd)
cli.add_command(show_timeline_cmd)
cli.add_command(show_threads_cmd)
cli.add_command(translate_titles_cmd)
cli.add_command(embed_evidence_cmd)
cli.add_command(match_jd_cmd)
cli.add_command(run_all_cmd)
cli.add_command(review_group)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
