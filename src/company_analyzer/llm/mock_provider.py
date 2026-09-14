from __future__ import annotations

import hashlib
import re

from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import EventCandidate

# Keyword family -> (event_type, stage-ish action word). Deliberately simple:
# the mock provider only needs to be good enough to exercise every downstream
# code path deterministically, not to approximate real extraction quality.
_ACTION_FAMILIES: dict[str, tuple[str, str]] = {
    "announce": ("strategy_announcement", "announce"),
    "unveil": ("strategy_announcement", "announce"),
    "reveal": ("strategy_announcement", "announce"),
    "plan to": ("strategy_announcement", "announce"),
    "develop": ("product_development", "build"),
    "invest": ("product_development", "build"),
    "pilot": ("pilot_program", "pilot"),
    "trial": ("pilot_program", "pilot"),
    "test with": ("pilot_program", "pilot"),
    "launch": ("product_launch", "launch"),
    "release": ("product_launch", "launch"),
    "roll out": ("product_launch", "launch"),
    "open to the public": ("product_launch", "launch"),
    "expand": ("expansion", "scale"),
    "scale": ("expansion", "scale"),
    "partner": ("partnership", "announce"),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


_ENTITY_STOPWORDS = {
    "the", "as", "we", "this", "it", "they", "our", "for", "with",
    "following", "part", "background", "rollout", "conclusion",
}


def _guess_entity(sentence: str) -> str | None:
    # Naive: first quoted phrase, else the first capitalized run that isn't a
    # common sentence-initial word (deterministic enough for test fixtures -
    # not a stand-in for real NER, which only a real provider would do).
    quoted = re.search(r"[\"'“]([^\"'”]{2,40})[\"'”]", sentence)
    if quoted:
        return quoted.group(1)
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]+(?:\s[A-Z0-9][a-zA-Z0-9]*){0,2})\b", sentence):
        candidate = match.group(1)
        if candidate.lower() not in _ENTITY_STOPWORDS and candidate != "NAVER":
            return candidate
    return None


class MockLLMProvider(LLMProvider):
    name = "mock"

    def extract_events(self, chunk_text: str, metadata: dict) -> list[EventCandidate]:
        candidates: list[EventCandidate] = []
        for sentence in _split_sentences(chunk_text):
            lowered = sentence.lower()
            for keyword, (event_type, action) in _ACTION_FAMILIES.items():
                if keyword in lowered:
                    candidates.append(
                        EventCandidate(
                            event_type=event_type,
                            subject=metadata.get("company"),
                            action=action,
                            event_date=metadata.get("published_date"),
                            date_precision="day" if metadata.get("published_date") else "unknown",
                            lifecycle_status="completed" if action in ("launch",) else "planned",
                            domain=metadata.get("domain"),
                            entity=_guess_entity(sentence),
                            raw_quote=sentence,
                        )
                    )
                    break  # one candidate per sentence is enough for deterministic tests
        return candidates

    def classify_relationship(self, event_a: dict, event_b: dict) -> dict:
        same_entity = bool(event_a.get("entity")) and event_a.get("entity") == event_b.get("entity")
        same_domain = bool(event_a.get("domain")) and event_a.get("domain") == event_b.get("domain")
        same_type = event_a.get("event_type") == event_b.get("event_type")

        if same_entity and same_type:
            return {
                "relationship_type": "same_event",
                "confidence": 0.9,
                "rationale": "Mock: same entity and same event_type.",
            }
        if same_entity or same_domain:
            return {
                "relationship_type": "related_distinct",
                "confidence": 0.7,
                "rationale": "Mock: shared entity/domain but different event_type.",
            }
        return {
            "relationship_type": "unrelated",
            "confidence": 0.6,
            "rationale": "Mock: no shared entity or domain.",
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * 32
            for word in re.findall(r"\w+", text.lower()):
                digest = hashlib.sha256(word.encode("utf-8")).digest()
                idx = digest[0] % 32
                vec[idx] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    def generate_title(self, fields: dict) -> str:
        label = fields.get("entity") or fields.get("domain") or fields.get("event_type") or "Event"
        action = fields.get("action")
        return f"{label}: {action}" if action and action != label else label

    def parse_job_description(self, raw_text: str) -> dict:
        # Deterministic enough to exercise the matching pipeline in tests -
        # every non-trivial sentence becomes a "task", nothing else parsed.
        tasks = [s for s in _split_sentences(raw_text) if len(s) > 5]
        return {
            "role": None,
            "role_subtype": None,
            "domain": None,
            "tasks": tasks,
            "entities": [],
            "skills": [],
        }
