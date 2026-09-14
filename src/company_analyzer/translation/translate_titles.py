from __future__ import annotations

import re

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.base import LLMProvider

_HANGUL_RE = re.compile(r"[가-힣]")
# _title_for()'s fallback format is "<entity>: <action>" - when only the
# action came from a pre-Korean-prompt extraction, the entity half can
# already be Korean (e.g. "ADVoost 쇼핑: launched") and contains_korean()
# alone would wrongly call that title "done". A colon directly followed by
# Latin letters is that exact leftover-English-action pattern.
_ENGLISH_ACTION_SUFFIX_RE = re.compile(r":\s*[A-Za-z]")
# The pre-fix _thread_title() always appended one of these two literal
# English words - same leftover-fragment problem, different shape.
_ENGLISH_THREAD_SUFFIX_RE = re.compile(r"\b(Expansion|Initiative)\s*$")


def contains_korean(text: str) -> bool:
    return bool(_HANGUL_RE.search(text))


def needs_translation(title: str) -> bool:
    if not contains_korean(title):
        return True
    if _ENGLISH_ACTION_SUFFIX_RE.search(title):
        return True
    return bool(_ENGLISH_THREAD_SUFFIX_RE.search(title))


def translate_canonical_event_titles(conn: DBConnection, company_id: int, provider: LLMProvider) -> int:
    """Backfill a natural Korean title for every canonical event whose title
    isn't (fully) Korean yet (skips ones already translated, so reruns after
    the background pipeline adds more events only pay for the new ones)."""
    count = 0
    for ce in repo.list_canonical_events(conn, company_id):
        if not needs_translation(ce.title):
            continue
        title = provider.generate_title(
            {
                "entity": ce.entity,
                "action": ce.action,
                "domain": ce.domain,
                "event_type": ce.event_type,
            }
        )
        repo.update_canonical_event_title(conn, ce.id, title)
        count += 1
        conn.commit()
    return count


def translate_thread_titles(conn: DBConnection, company_id: int, provider: LLMProvider) -> int:
    count = 0
    for thread in repo.list_threads(conn, company_id):
        if not needs_translation(thread.title):
            continue
        title = provider.generate_title({"entity": thread.entity, "domain": thread.domain})
        repo.update_thread_title(conn, thread.id, title)
        count += 1
        conn.commit()
    return count
