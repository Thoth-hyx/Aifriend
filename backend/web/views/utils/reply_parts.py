import re


# Require actual next content before closing a bubble, keeping punctuation/quotes together.
TOKENS = re.compile(
    r'```|~~~|(?:[。！？]+[。！？!?]*[”’"』」）)\]]*'
    r'|(?<!\d)[.!?][”’"』」）)\]]*(?=\s)|\n[^\S\n]*\n)'
    r'\s*(?=[^\s。！？!?.”’"』」）)\]])'
)


class ReplyStream:
    """Append-only streaming segmentation; already displayed bubbles never move."""

    def __init__(self):
        self.closed = []
        self.buffer = ''
        self.emitted = 0

    def boundary(self):
        # ponytail: sentence/fence heuristics; use structured segments for exact Markdown semantics.
        fence = None
        for match in TOKENS.finditer(self.buffer):
            token = match.group()
            if token in ('```', '~~~'):
                if fence is None:
                    fence = token
                elif fence == token:
                    fence = None
            elif fence is None:
                return match.end()
        return None

    def feed(self, content):
        self.buffer += content
        if not self.emitted:
            self.buffer = self.buffer.lstrip()
        events = []
        while len(self.closed) < 2:
            boundary = self.boundary()
            if boundary is None:
                break
            head = self.buffer[:boundary].rstrip()
            self.emit(head, events)
            self.closed.append(head)
            self.buffer = self.buffer[boundary:].lstrip()
            self.emitted = 0
        self.emit(self.buffer.rstrip(), events)
        return events

    def emit(self, text, events):
        delta = text[self.emitted:]
        if delta:
            events.append({'part_index': len(self.closed), 'content': delta})
        self.emitted = len(text)

    @property
    def parts(self):
        tail = self.buffer.rstrip()
        return self.closed + ([tail] if tail else [])


def split_reply(content):
    stream = ReplyStream()
    stream.feed(content)
    return stream.parts
