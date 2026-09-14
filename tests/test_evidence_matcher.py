from __future__ import annotations

from company_analyzer.evidence.matcher import fuzzy_locate

CHUNK = (
    "NAVER announced today that it will expand its AI-powered search service "
    "to cover additional product categories starting this quarter. The company "
    "plans to invest heavily in infrastructure to support the expanded AI "
    "search capabilities."
)


def test_exact_quote_matches_with_score_one():
    quote = "NAVER announced today that it will expand its AI-powered search service"
    result = fuzzy_locate(quote, CHUNK)
    assert result.method == "exact"
    assert result.is_valid is True
    assert result.score == 1.0
    assert result.matched_text == quote


def test_whitespace_and_quote_mangled_text_still_matches_exactly():
    quote = "NAVER   announced today that it will expand its\n\nAI-powered search service"
    result = fuzzy_locate(quote, CHUNK)
    assert result.method == "exact"
    assert result.is_valid is True


def test_lightly_paraphrased_quote_is_accepted_via_fuzzy_match():
    # Small paraphrase (word substitution) - close enough to pass rapidfuzz's
    # partial-ratio threshold, but not an exact substring.
    quote = "NAVER announced today that it will grow its AI-powered search service"
    result = fuzzy_locate(quote, CHUNK)
    assert result.method == "fuzzy_rapidfuzz"
    assert result.is_valid is True
    assert result.matched_text is not None


def test_heavily_paraphrased_quote_is_rejected():
    quote = "The company revealed a totally new blockchain payment platform for retail banking."
    result = fuzzy_locate(quote, CHUNK)
    assert result.is_valid is False
    assert result.method == "rejected"
    assert result.matched_text is None


def test_empty_quote_is_rejected():
    result = fuzzy_locate("", CHUNK)
    assert result.is_valid is False
    assert result.method == "rejected"


def test_too_short_match_is_rejected_even_if_similar():
    result = fuzzy_locate("AI", CHUNK)
    assert result.is_valid is False


def test_matched_span_reconstructs_from_original_chunk_text():
    quote = "plans to invest heavily in infrastructure"
    result = fuzzy_locate(quote, CHUNK)
    assert result.is_valid is True
    assert CHUNK[result.start:result.end] == result.matched_text
