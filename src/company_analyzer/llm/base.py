from __future__ import annotations

from abc import ABC, abstractmethod

from company_analyzer.models import EventCandidate

PROMPT_VERSION = "v2"


class LLMProvider(ABC):
    """Provider-agnostic interface for extraction, relationship classification, and embeddings.

    Implementations: MockLLMProvider (no network, deterministic), and stubs for
    AnthropicProvider / OpenAIProvider to be filled in once a vendor is chosen.
    """

    name: str

    @abstractmethod
    def extract_events(self, chunk_text: str, metadata: dict) -> list[EventCandidate]:
        """Return zero or more event candidates found in chunk_text.

        metadata carries context the model should use: company, source_type,
        published_date, heading. Returning an empty list is a valid "no event
        here" response - the extractor must not force at least one event.
        """

    @abstractmethod
    def classify_relationship(self, event_a: dict, event_b: dict) -> dict:
        """Classify the relationship between two events.

        event_a/event_b are dicts with the event's attributes plus its
        validated evidence text. Returns a dict with keys:
        relationship_type ('same_event'|'related_distinct'|'unrelated'|'insufficient_info'),
        confidence (0..1), rationale (str).
        """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""

    @abstractmethod
    def generate_title(self, fields: dict) -> str:
        """Return a short natural-language display title summarizing an
        event or thread from its attributes (entity, action, domain,
        event_type - whichever are present in `fields`). Real providers
        should always answer in Korean; MockLLMProvider does not (no
        translation quality to prove in tests, only mechanics)."""

    @abstractmethod
    def parse_job_description(self, raw_text: str) -> dict:
        """Parse a pasted job description into a dict with keys: role,
        role_subtype, domain, tasks (list[str]), entities (list[str]),
        skills (list[str]). Preserve the JD's own language - do not translate."""

    def supports_embeddings(self) -> bool:
        return True
