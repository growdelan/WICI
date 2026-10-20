"""Keep readable source text while discarding executable and interface markup."""
import re
from html.parser import HTMLParser


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'iframe', 'object', 'video', 'audio'):
            self.hidden += 1
        elif tag in ('p', 'br', 'div', 'li') and not self.hidden:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'iframe', 'object', 'video', 'audio'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_text(text: str) -> str:
    parser = _Text()
    parser.feed(text)
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()
