from __future__ import annotations

from company_analyzer.chunking.base import ChunkDraft, find_paragraphs

MIN_PARAGRAPH_LENGTH = 20


def chunk_by_paragraph(raw_text: str, min_length: int = MIN_PARAGRAPH_LENGTH) -> list[ChunkDraft]:
    """Press releases: split on blank-line-delimited paragraphs, drop short
    boilerplate/dateline fragments."""
    return [
        {"heading": None, "text": text, "start_offset": start, "end_offset": end}
        for start, end, text in find_paragraphs(raw_text, min_length=min_length)
    ]
