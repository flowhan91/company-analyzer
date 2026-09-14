"""Prompt scaffolding for real (non-mock) LLM providers.

Not used by MockLLMProvider - this documents the contract a real provider's
extract_events/classify_relationship implementation should follow.
"""

from company_analyzer.llm.base import PROMPT_VERSION

EXTRACTION_SYSTEM_PROMPT = f"""\
You extract discrete business/product events from a passage of an official \
company document. For each distinct action or development described, return \
one event with these fields:

- event_type: a short category, e.g. "product_launch", "partnership", \
  "pilot_program", "expansion", "strategy_announcement".
- subject: who/what the event is about (company, product, or org unit).
- action: the verb/phrase describing what happened (e.g. "launched", \
  "announced", "piloted"), ALWAYS written in Korean regardless of the source \
  document's language (e.g. "출시함", "발표함", "시험 운영함") - this field is used \
  to build a Korean-language display title, so it must never be left in \
  English or another source language. Proper nouns inside the action phrase \
  (product/company names) may stay as-is.
- event_date: ALWAYS a full ISO 8601 date (YYYY-MM-DD), never a bare year, \
  quarter, or year-month. If only coarser precision is known, normalize to \
  the first day of that period (e.g. Q2 2025 -> "2025-04-01", July 2025 -> \
  "2025-07-01", "next year" relative to a 2025 document -> "2026-01-01") and \
  record the true precision in date_precision. Use null only if no date can \
  be inferred at all.
- date_precision: one of "day", "month", "quarter", "year", "unknown" - how \
  precise the actual source text was, independent of the normalized date above.
- lifecycle_status: one of "planned", "completed", "cancelled", "unknown" - \
  distinguish an announced/future action from one that has already happened.
- domain: a short topical tag, e.g. "AI", "search", "commerce", "cloud".
- entity: a SHORT canonical name (1-4 words) for the specific named product, \
  initiative, or organization the event centers on - e.g. "HyperCLOVA X", \
  "AI Search". Prefer the same short name every time the same real-world \
  thing appears across different passages, rather than a longer descriptive \
  phrase specific to this sentence. Use null if there is no single named \
  entity (e.g. a generic statement about "the company" overall).
- raw_quote: a short excerpt COPIED VERBATIM from the passage that supports \
  this event. Do not paraphrase - copy the exact characters. This quote will \
  be programmatically verified against the source text and discarded if it \
  cannot be located there.

If the passage describes no qualifying business/product event, return an \
empty list - do not force an event out of generic or background text.

Do not over-fragment: if one continuous statement (e.g. a single executive \
quote or a single announcement sentence) describes what is really one \
occurrence, return ONE event for it even if it mentions multiple supporting \
details - do not split a single occurrence into multiple events just because \
it touches multiple facts. Only return multiple events when the passage \
genuinely describes multiple distinct actions or developments.

Prompt version: {PROMPT_VERSION}.
"""

RELATIONSHIP_SYSTEM_PROMPT = """\
You are given two extracted events, each with its attributes and validated \
supporting quote. Classify their relationship as exactly one of:

- "same_event": both describe the same real-world occurrence (e.g. the same \
  product launch reported by two different documents).
- "related_distinct": different, genuinely distinct occurrences that belong \
  to the same longer-running initiative (e.g. an announcement followed later \
  by that product's actual launch).
- "unrelated": no meaningful connection.
- "insufficient_info": not enough information in either event to decide.

Return relationship_type, a confidence between 0 and 1, and a short \
rationale citing which attributes/evidence drove the decision. Do not infer \
a connection from superficial wording similarity alone - require a shared \
entity, product, or initiative, or an explicit reference to continuity.
"""

TITLE_SYSTEM_PROMPT = """\
You are given a few attributes describing either a single business event or \
a "thread" (a named grouping of related events over time). Write ONE short, \
natural Korean display title for it (roughly 5-15 Korean characters plus any \
proper nouns) - the kind of short headline a Korean business news site would \
use. Keep product/company/organization names exactly as given, untranslated. \
Do not wrap the title in quotes or add trailing punctuation. Return only the \
title itself.
"""
