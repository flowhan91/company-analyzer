from __future__ import annotations

import re

# DART periodic reports (사업보고서/분기보고서/반기보고서) bundle everything
# into one document: company overview, business description, full financial
# statements, audit report, governance appendices. A real annual report ran
# to 798,839 chars / 7,250 chunks unscoped - the overwhelming majority of it
# is financial-statement tables with zero business/product events to find.
# The narrative content worth extracting lives specifically in the
# "사업의 내용" (business content) section, a standard top-level heading
# bounded by the next top-level Roman-numeral section (e.g. "III. 재무에 관한
# 사항"). Scoping to just that section cut one real quarterly report from
# 148,611 chars / 1,215 chunks down to ~43,000 chars.
PERIODIC_REPORT_TITLE_RE = re.compile(r"(사업보고서|분기보고서|반기보고서)")
_TOP_LEVEL_HEADING_RE = re.compile(r"^([IVXLCDM]+)\.\s+(.+)$", re.MULTILINE)
_BUSINESS_SECTION_KEYWORD = "사업의 내용"


def is_periodic_report(title: str) -> bool:
    return bool(PERIODIC_REPORT_TITLE_RE.search(title))


def scope_to_business_section(raw_text: str) -> tuple[str, int]:
    """Return (scoped_substring, offset_baseline) for a periodic report's
    raw_text, limited to the business-content section. Falls back to the
    full text (offset_baseline=0) if the heading isn't found - better to
    over-chunk than silently produce nothing."""
    matches = list(_TOP_LEVEL_HEADING_RE.finditer(raw_text))
    start_idx = None
    for i, match in enumerate(matches):
        if _BUSINESS_SECTION_KEYWORD in match.group(2):
            start_idx = i
            break
    if start_idx is None:
        return raw_text, 0

    start = matches[start_idx].start()
    end = matches[start_idx + 1].start() if start_idx + 1 < len(matches) else len(raw_text)
    return raw_text[start:end], start
