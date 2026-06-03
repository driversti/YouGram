"""Split a long reply into Telegram-sized chunks.

Telegram rejects a single message over 4096 UTF-16 units (`MessageTooLongError`).
`split_message` packs text into chunks no larger than `limit`, preferring to
break on line boundaries, then word boundaries, and only hard-cutting a single
token that is itself longer than the limit.
"""

# Below Telegram's 4096 hard cap: emoji and formatting count as more than one
# UTF-16 unit, so we leave headroom to stay under the real limit.
DEFAULT_LIMIT = 4000


def split_message(text: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Split `text` into chunks, each at most `limit` characters.

    Breaks on the last newline within the limit; failing that, the last space;
    failing that (a single oversized token), a hard cut. Boundary whitespace is
    consumed, so chunks rejoin cleanly. Never emits an empty chunk.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut, skip = window.rfind("\n"), 1
        if cut <= 0:  # no usable newline — try a word boundary
            cut = window.rfind(" ")
        if cut <= 0:  # a single token longer than the limit — hard cut, lose nothing
            cut, skip = limit, 0
        chunks.append(remaining[:cut])
        remaining = remaining[cut + skip:]
    if remaining:
        chunks.append(remaining)
    return chunks
