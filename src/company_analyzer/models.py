from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    id: int
    name: str
    dart_corp_code: str | None
    aliases: list[str]


@dataclass(frozen=True)
class Document:
    id: int
    company_id: int
    source_type: str  # dart | ir | press_release | tech_blog | ceo_letter | news
    is_official: bool
    title: str
    url: str | None
    published_date: str | None
    external_id: str
    file_path: str | None
    raw_text: str
    content_hash: str
    version: int
    fetched_at: str
    metadata: dict


@dataclass(frozen=True)
class DocumentSnapshot:
    id: int
    document_id: int
    version: int
    raw_text: str
    content_hash: str
    fetched_at: str


@dataclass(frozen=True)
class IngestionLogEntry:
    id: int
    source: str  # dart | news | manual
    company_id: int
    status: str  # success | failed
    detail: str | None
    error_message: str | None
    occurred_at: str


@dataclass(frozen=True)
class Chunk:
    id: int
    document_id: int
    chunk_index: int
    heading: str | None
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class EventCandidate:
    """LLM extraction output, pre-persistence."""

    event_type: str
    subject: str | None
    action: str | None
    event_date: str | None
    date_precision: str  # day | month | quarter | year | unknown
    lifecycle_status: str  # planned | completed | cancelled | unknown
    domain: str | None
    entity: str | None
    raw_quote: str


@dataclass(frozen=True)
class Event:
    id: int
    chunk_id: int
    event_type: str
    subject: str | None
    action: str | None
    event_date: str | None
    date_precision: str
    lifecycle_status: str
    domain: str | None
    entity: str | None
    raw_quote: str
    extraction_model: str
    prompt_version: str
    llm_raw_response_json: str | None
    created_at: str


@dataclass(frozen=True)
class EvidenceSpan:
    id: int
    event_id: int
    chunk_id: int
    raw_quote: str
    matched_text: str | None
    start_offset: int | None
    end_offset: int | None
    match_score: float
    match_method: str  # exact | fuzzy_rapidfuzz | rejected
    is_valid: bool
    review_status: str  # auto_valid | pending | approved | rejected
    validated_at: str
    embedding: list[float] | None = None


@dataclass(frozen=True)
class EventRelationship:
    id: int
    event_a_id: int
    event_b_id: int
    relationship_type: str  # same_event | related_distinct | unrelated | insufficient_info
    rationale: str | None
    confidence: float
    decided_by: str  # llm | human
    review_status: str  # auto_applied | pending | approved | rejected
    created_at: str


@dataclass(frozen=True)
class CanonicalEventRelationship:
    id: int
    canonical_event_a_id: int
    canonical_event_b_id: int
    relationship_type: str  # same_event | related_distinct | unrelated | insufficient_info
    rationale: str | None
    confidence: float
    decided_by: str  # llm | human
    review_status: str  # auto_applied | pending | approved | rejected
    created_at: str


@dataclass(frozen=True)
class CanonicalEvent:
    id: int
    company_id: int
    event_type: str
    subject: str | None
    action: str | None
    canonical_date: str | None
    date_precision: str
    lifecycle_status: str
    domain: str | None
    entity: str | None
    title: str
    summary: str | None
    stage: str | None
    review_status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Thread:
    id: int
    company_id: int
    title: str
    domain: str | None
    entity: str | None
    review_status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ThreadEvent:
    id: int
    thread_id: int
    canonical_event_id: int
    sequence_index: int
    stage: str | None
    relationship_id: int | None


@dataclass(frozen=True)
class UserJD:
    id: int
    company_id: int
    raw_text: str
    role: str | None
    role_subtype: str | None
    domain: str | None
    entities: list[str]
    tasks: list[str]
    created_at: str
