from html.parser import HTMLParser
import re


class DefensiveParser:
    """Defensive HTML URL extractor using html.parser with a regex fallback."""

    _ATTR_URL_RE = re.compile(
        r"(?P<attr>href|src|action|formaction|data|poster)\s*=\s*['\"](?P<url>.*?)['\"]",
        re.IGNORECASE | re.DOTALL,
    )
    _UNQUOTED_ATTR_URL_RE = re.compile(
        r"(?P<attr>href|src|action|formaction|data|poster)\s*=\s*(?P<url>[^>\s'\"]+)",
        re.IGNORECASE,
    )
    _SRCSET_RE = re.compile(
        r'''srcset\s*=\s*(['"])(?P<value>.*?)\1''', 
        re.IGNORECASE | re.DOTALL
    )

    def extract_urls(self, html):
        """Return all unique URLs found in HTML, using parser first and regex as fallback."""
        parser = self._LinkExtractor()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            # html.parser can fail on extremely malformed HTML; fallback below
            pass

        if parser.urls:
            return list(parser.urls)

        return self._regex_fallback(html)

    class _LinkExtractor(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.urls = []
            self._seen = set()

        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if not value:
                    continue

                name = name.lower()
                if name in {"href", "src", "action", "formaction", "data", "poster"}:
                    self._add_url(value)
                elif name == "srcset":
                    for url in self._split_srcset(value):
                        self._add_url(url)

        def _add_url(self, url):
            url = url.strip()
            if url and url not in self._seen:
                self._seen.add(url)
                self.urls.append(url)

        @staticmethod
        def _split_srcset(value):
            for part in value.split(","):
                part = part.strip()
                if not part:
                    continue
                yield part.split()[0]

    def _regex_fallback(self, html):
        urls = []
        seen = set()

        def add(url):
            url = url.strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for match in self._ATTR_URL_RE.finditer(html):
            add(match.group("url"))

        for match in self._UNQUOTED_ATTR_URL_RE.finditer(html):
            add(match.group("url"))

        for match in self._SRCSET_RE.finditer(html):
            for url in self._split_srcset(match.group("value")):
                add(url)

        return urls

    @staticmethod
    def _split_srcset(value):
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            yield part.split()[0]
