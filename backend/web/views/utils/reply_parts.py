import re


def split_reply(content):
    """Display one complete reply as at most three natural message bubbles."""
    text = content.strip()
    if not text:
        return []
    # ponytail: keep fenced code intact; use a Markdown parser if block-level splitting is needed.
    if '```' in text or '~~~' in text:
        return [text]
    pieces = re.split(r'\n\s*\n', text)
    if len(pieces) == 1 and '\n' not in text:
        pieces = re.split(r'(?<=[。！？])\s*|(?<=[.!?])\s+', text)
    pieces = [piece.strip() for piece in pieces if piece.strip()]
    return pieces[:2] + ['\n\n'.join(pieces[2:])] if len(pieces) > 3 else pieces
