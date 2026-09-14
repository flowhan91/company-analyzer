from __future__ import annotations

import re

from company_analyzer.chunking.base import ChunkDraft, find_paragraphs, make_draft

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
MAX_SECTION_LENGTH = 1500


def chunk_by_heading_and_paragraph(raw_text: str, max_section_length: int = MAX_SECTION_LENGTH) -> list[ChunkDraft]:
    """Tech blog posts / CEO letters: split on markdown headings first, then
    further split any oversized section into paragraphs (keeping the heading
    attached to each sub-chunk for context)."""
    matches = list(_MD_HEADING_RE.finditer(raw_text))
    if not matches:
        return [
            {"heading": None, "text": text, "start_offset": start, "end_offset": end}
            for start, end, text in find_paragraphs(raw_text, min_length=0)
        ]

    drafts: list[ChunkDraft] = []
    for i, match in enumerate(matches):
        section_start = match.start()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        heading_text = match.group().strip()

        if section_end - section_start <= max_section_length:
            draft = make_draft(raw_text, section_start, section_end, heading=heading_text)
            if draft is not None:
                drafts.append(draft)
            continue

        # Oversized section: split into paragraphs within [section_start, section_end).
        body_start = match.end()
        section_text = raw_text[body_start:section_end]
        for para_start, para_end, _ in find_paragraphs(section_text, min_length=0):
            draft = make_draft(raw_text, body_start + para_start, body_start + para_end, heading=heading_text)
            if draft is not None:
                drafts.append(draft)
    return drafts
