from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from company_analyzer.evidence.normalize import normalize_text, normalize_with_offsets

ACCEPT_SCORE = 0.85
REVIEW_FLOOR_SCORE = 0.60
MIN_MATCH_LENGTH = 15
MAX_LENGTH_RATIO = 2.0


@dataclass(frozen=True)
class MatchResult:
    start: int | None  # offset into the chunk's local text
    end: int | None
    matched_text: str | None
    score: float  # 0..1
    method: str  # 'exact' | 'fuzzy_rapidfuzz' | 'rejected'
    is_valid: bool


def _sanity_check(matched_text: str, quote_len: int) -> bool:
    if len(matched_text) < MIN_MATCH_LENGTH:
        return False
    if quote_len > 0 and len(matched_text) > quote_len * MAX_LENGTH_RATIO:
        return False
    return True


def fuzzy_locate(quote: str, chunk_text: str) -> MatchResult:
    """Locate `quote` (an LLM's claimed verbatim excerpt) inside `chunk_text`.

    Never trusts the quote as-is: tries an exact match first (after
    normalization), falls back to rapidfuzz's alignment-aware partial match,
    and rejects (fails closed) anything that doesn't clear ACCEPT_SCORE with
    a sane match length. Matches between REVIEW_FLOOR_SCORE and ACCEPT_SCORE
    are returned but marked invalid, for human review rather than silent use.
    """
    quote_stripped = quote.strip() if quote else ""
    if not quote_stripped:
        return MatchResult(None, None, None, 0.0, "rejected", False)

    norm_quote = normalize_text(quote_stripped)
    norm_chunk, offset_map = normalize_with_offsets(chunk_text)
    if not norm_quote or not norm_chunk:
        return MatchResult(None, None, None, 0.0, "rejected", False)

    def to_original_span(dest_start: int, dest_end: int) -> tuple[int, int]:
        dest_end = max(dest_end, dest_start + 1)
        dest_start = min(dest_start, len(offset_map) - 1)
        dest_end = min(dest_end, len(offset_map))
        start_orig = offset_map[dest_start]
        end_orig = offset_map[dest_end - 1] + 1
        return start_orig, end_orig

    # 1. Exact match fast path.
    idx = norm_chunk.find(norm_quote)
    if idx != -1:
        start_orig, end_orig = to_original_span(idx, idx + len(norm_quote))
        matched_text = chunk_text[start_orig:end_orig]
        if _sanity_check(matched_text, len(quote_stripped)):
            return MatchResult(start_orig, end_orig, matched_text, 1.0, "exact", True)

    # 2. Fuzzy fallback: rapidfuzz locates the best-aligned window itself.
    alignment = fuzz.partial_ratio_alignment(norm_quote, norm_chunk)
    score = alignment.score / 100.0
    start_orig, end_orig = to_original_span(alignment.dest_start, alignment.dest_end)
    matched_text = chunk_text[start_orig:end_orig]

    if score >= ACCEPT_SCORE and _sanity_check(matched_text, len(quote_stripped)):
        return MatchResult(start_orig, end_orig, matched_text, score, "fuzzy_rapidfuzz", True)

    if score >= REVIEW_FLOOR_SCORE and _sanity_check(matched_text, len(quote_stripped)):
        return MatchResult(start_orig, end_orig, matched_text, score, "fuzzy_rapidfuzz", False)

    return MatchResult(None, None, None, score, "rejected", False)
