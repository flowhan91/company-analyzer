from __future__ import annotations

from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import EventCandidate


class AnthropicProvider(LLMProvider):
    """Stub - wire up against the Claude API once this provider is chosen.

    The interface is final; only the bodies need implementing:
    - extract_events: send extraction/prompts.py's template + chunk_text, parse
      structured JSON output into EventCandidate list.
    - classify_relationship: send both events' attributes + evidence, parse the
      relationship_type/confidence/rationale JSON.
    - embed: Claude has no native embeddings endpoint - either call a separate
      embeddings provider here, or set supports_embeddings() to False and let
      clustering/threading fall back to non-embedding signals.
    """

    name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def extract_events(self, chunk_text: str, metadata: dict) -> list[EventCandidate]:
        raise NotImplementedError("AnthropicProvider.extract_events is not implemented yet.")

    def classify_relationship(self, event_a: dict, event_b: dict) -> dict:
        raise NotImplementedError("AnthropicProvider.classify_relationship is not implemented yet.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("AnthropicProvider.embed is not implemented yet.")

    def generate_title(self, fields: dict) -> str:
        raise NotImplementedError("AnthropicProvider.generate_title is not implemented yet.")

    def parse_job_description(self, raw_text: str) -> dict:
        raise NotImplementedError("AnthropicProvider.parse_job_description is not implemented yet.")

    def supports_embeddings(self) -> bool:
        return False
