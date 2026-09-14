from __future__ import annotations

from company_analyzer.chunking.base import Chunker, ChunkDraft
from company_analyzer.chunking.dart_scope import is_periodic_report, scope_to_business_section
from company_analyzer.chunking.heading_paragraph_chunker import chunk_by_heading_and_paragraph
from company_analyzer.chunking.overlap_paragraph_chunker import chunk_with_overlap
from company_analyzer.chunking.paragraph_chunker import chunk_by_paragraph
from company_analyzer.chunking.section_chunker import chunk_by_section

_CHUNKERS: dict[str, Chunker] = {
    "dart": chunk_by_section,
    "ir": chunk_by_section,
    "press_release": chunk_by_paragraph,
    "tech_blog": chunk_by_heading_and_paragraph,
    "ceo_letter": chunk_by_heading_and_paragraph,
    "news": chunk_with_overlap,
}


def get_chunker(source_type: str) -> Chunker:
    try:
        return _CHUNKERS[source_type]
    except KeyError:
        raise ValueError(f"No chunker registered for source_type '{source_type}'") from None


def chunk_document(source_type: str, title: str, raw_text: str) -> list[ChunkDraft]:
    """Chunk a document's raw_text, applying source-type-specific scoping
    before dispatch. DART periodic reports (사업보고서/분기보고서/반기보고서)
    get scoped to their business-content section first - see
    chunking.dart_scope for why (a real annual report was 798K chars /
    7,250 chunks unscoped, ~29K chars once scoped). Offsets in the returned
    drafts are always relative to the full raw_text passed in, regardless
    of scoping.
    """
    text_to_chunk = raw_text
    offset_baseline = 0
    if source_type == "dart" and is_periodic_report(title):
        text_to_chunk, offset_baseline = scope_to_business_section(raw_text)

    chunker = get_chunker(source_type)
    drafts = chunker(text_to_chunk)
    if offset_baseline:
        for draft in drafts:
            draft["start_offset"] += offset_baseline
            draft["end_offset"] += offset_baseline
    return drafts
