"""Boundary-aware chunking: ~500 tokens with 80 overlap (SRS §10.3).

Tokens are approximated as 4 characters. Paragraphs (blank-line separated,
which includes headings) are packed whole when possible; oversized paragraphs
are split on sentence/word boundaries.
"""
import re

CHARS_PER_TOKEN = 4
CHUNK_CHARS = 500 * CHARS_PER_TOKEN
OVERLAP_CHARS = 80 * CHARS_PER_TOKEN


def _split_long(paragraph: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > limit:  # no sentence boundary: cut on a word boundary
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    tail = text[-size:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_text(
    text: str, chunk_chars: int = CHUNK_CHARS, overlap_chars: int = OVERLAP_CHARS
) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for p in paragraphs:
        units.extend(_split_long(p, chunk_chars) if len(p) > chunk_chars else [p])

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 2 + len(unit) > chunk_chars:
            chunks.append(current)
            tail = _overlap_tail(current, overlap_chars)
            current = f"{tail}\n\n{unit}" if len(tail) + 2 + len(unit) <= chunk_chars else unit
        else:
            current = f"{current}\n\n{unit}" if current else unit
    if current:
        chunks.append(current)
    return chunks
