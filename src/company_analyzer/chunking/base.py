from __future__ import annotations

import re
from typing import Callable

ChunkDraft = dict  # {"heading": str | None, "text": str, "start_offset": int, "end_offset": int}
Chunker = Callable[[str], list[ChunkDraft]]

# Matches blocks of consecutive non-blank lines - i.e. "paragraphs" separated
# by one or more blank (possibly whitespace-only) lines.
_PARAGRAPH_RE = re.compile(r"[^\n]+(?:\n[^\n]+)*")


def trim_span(raw_text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink [start, end) to exclude leading/trailing whitespace, so that
    raw_text[new_start:new_end] is exactly the trimmed text - the offset
    invariant every chunker must preserve."""
    segment = raw_text[start:end]
    lstripped = segment.lstrip()
    left_trim = len(segment) - len(lstripped)
    rstripped = lstripped.rstrip()
    right_trim = len(lstripped) - len(rstripped)
    return start + left_trim, end - right_trim


def find_paragraphs(raw_text: str, min_length: int = 0) -> list[tuple[int, int, str]]:
    """Return (start, end, text) for each paragraph, offsets exact into raw_text."""
    results = []
    for m in _PARAGRAPH_RE.finditer(raw_text):
        start, end = trim_span(raw_text, m.start(), m.end())
        if end <= start:
            continue
        text = raw_text[start:end]
        if len(text) < min_length:
            continue
        results.append((start, end, text))
    return results


def make_draft(raw_text: str, start: int, end: int, heading: str | None = None) -> ChunkDraft | None:
    start, end = trim_span(raw_text, start, end)
    if end <= start:
        return None
    return {"heading": heading, "text": raw_text[start:end], "start_offset": start, "end_offset": end}
