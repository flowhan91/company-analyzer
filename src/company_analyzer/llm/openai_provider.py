from __future__ import annotations

from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from company_analyzer.extraction.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    RELATIONSHIP_SYSTEM_PROMPT,
    TITLE_SYSTEM_PROMPT,
)
from company_analyzer.jd_matching.prompts import JD_PARSE_SYSTEM_PROMPT
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import EventCandidate

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
# A real clustering run hung indefinitely on what was almost certainly a
# stalled request - the SDK's default timeout is generous enough that a
# single bad connection can block a whole batch job for a very long time.
# Fail fast and let the caller's own retry/skip logic (if any) take over.
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 1


class _ExtractedEvent(BaseModel):
    event_type: str
    subject: str | None
    action: str | None
    event_date: str | None
    date_precision: Literal["day", "month", "quarter", "year", "unknown"]
    lifecycle_status: Literal["planned", "completed", "cancelled", "unknown"]
    domain: str | None
    entity: str | None
    raw_quote: str


class _ExtractionResult(BaseModel):
    events: list[_ExtractedEvent]


class _RelationshipResult(BaseModel):
    relationship_type: Literal["same_event", "related_distinct", "unrelated", "insufficient_info"]
    confidence: float
    rationale: str


class _TitleResult(BaseModel):
    title: str


class _JDParseResult(BaseModel):
    role: str | None
    role_subtype: str | None
    domain: str | None
    tasks: list[str]
    entities: list[str]
    skills: list[str]


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, embedding_model: str = DEFAULT_EMBEDDING_MODEL):
        self.client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
        self.model = model
        self.embedding_model = embedding_model

    def extract_events(self, chunk_text: str, metadata: dict) -> list[EventCandidate]:
        context = (
            f"Company: {metadata.get('company')}\n"
            f"Source type: {metadata.get('source_type')}\n"
            f"Published date: {metadata.get('published_date')}\n"
            f"Heading: {metadata.get('heading')}\n\n"
            f"Passage:\n{chunk_text}"
        )
        response = self.client.responses.parse(
            model=self.model,
            instructions=EXTRACTION_SYSTEM_PROMPT,
            input=context,
            text_format=_ExtractionResult,
            reasoning={"effort": "low"},
        )
        result = response.output_parsed
        return [
            EventCandidate(
                event_type=e.event_type,
                subject=e.subject,
                action=e.action,
                event_date=e.event_date,
                date_precision=e.date_precision,
                lifecycle_status=e.lifecycle_status,
                domain=e.domain,
                entity=e.entity,
                raw_quote=e.raw_quote,
            )
            for e in result.events
        ]

    def classify_relationship(self, event_a: dict, event_b: dict) -> dict:
        context = (
            "Event A:\n"
            f"{event_a}\n\n"
            "Event B:\n"
            f"{event_b}"
        )
        response = self.client.responses.parse(
            model=self.model,
            instructions=RELATIONSHIP_SYSTEM_PROMPT,
            input=context,
            text_format=_RelationshipResult,
            reasoning={"effort": "low"},
        )
        result = response.output_parsed
        return {
            "relationship_type": result.relationship_type,
            "confidence": result.confidence,
            "rationale": result.rationale,
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.embedding_model, input=texts)
        return [item.embedding for item in response.data]

    def generate_title(self, fields: dict) -> str:
        context = "\n".join(f"{key}: {value}" for key, value in fields.items() if value)
        response = self.client.responses.parse(
            model=self.model,
            instructions=TITLE_SYSTEM_PROMPT,
            input=context,
            text_format=_TitleResult,
            reasoning={"effort": "low"},
        )
        return response.output_parsed.title.strip()

    def parse_job_description(self, raw_text: str) -> dict:
        response = self.client.responses.parse(
            model=self.model,
            instructions=JD_PARSE_SYSTEM_PROMPT,
            input=raw_text,
            text_format=_JDParseResult,
            reasoning={"effort": "low"},
        )
        result = response.output_parsed
        return {
            "role": result.role,
            "role_subtype": result.role_subtype,
            "domain": result.domain,
            "tasks": result.tasks,
            "entities": result.entities,
            "skills": result.skills,
        }
