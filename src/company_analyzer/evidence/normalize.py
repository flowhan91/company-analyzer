from __future__ import annotations

_QUOTE_MAP = {
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "«": '"', "»": '"',
}


def normalize_char(ch: str) -> str | None:
    """Map a single character to its normalized form, or None if it should be
    dropped entirely (collapsed whitespace). Kept 1-input/at-most-1-output so
    callers can build an exact index map back to the original string."""
    if ch in _QUOTE_MAP:
        return _QUOTE_MAP[ch]
    if ch.isspace():
        return " "
    return ch.lower()


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalize text for comparison while keeping an index map so any offset
    into the normalized string can be mapped back to the original.

    Returns (normalized_text, offset_map) where offset_map[i] is the index in
    `text` that normalized_text[i] came from. Whitespace runs collapse to a
    single space (mapped to the run's first original index).
    """
    out_chars: list[str] = []
    offset_map: list[int] = []
    prev_was_space = False
    for i, ch in enumerate(text):
        mapped = normalize_char(ch)
        if mapped is None:
            continue
        if mapped == " ":
            if prev_was_space:
                continue
            prev_was_space = True
        else:
            prev_was_space = False
        out_chars.append(mapped)
        offset_map.append(i)
    return "".join(out_chars), offset_map


def normalize_text(text: str) -> str:
    normalized, _ = normalize_with_offsets(text)
    return normalized.strip()
