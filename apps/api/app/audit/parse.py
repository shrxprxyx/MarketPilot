"""Single-pass HTML extraction for the on-page checks (FR-AUD-03). Uses the standard-library
parser, which tolerates broken markup, so no HTML dependency is needed."""
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class PageData:
    title: str | None = None
    meta_description: str | None = None
    viewport: str | None = None
    canonical: str | None = None
    robots_meta: str | None = None
    h1_count: int = 0
    headings: list[str] = field(default_factory=list)  # h1-h3 text, for topic analysis
    images: int = 0
    images_missing_alt: int = 0
    open_graph: set[str] = field(default_factory=set)  # og:* property names present
    has_structured_data: bool = False
    links: list[str] = field(default_factory=list)  # raw href values of <a> tags


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.data = PageData()
        self._capture: str | None = None  # tag whose text is being collected
        self._buf: list[str] = []
        self._ld_json = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        d = self.data
        if tag in ("title", "h1", "h2", "h3"):
            self._capture, self._buf = tag, []
            if tag == "h1":
                d.h1_count += 1
        elif tag == "meta":
            name = a.get("name", "").lower()
            prop = a.get("property", "").lower()
            content = a.get("content", "").strip()
            if name == "description" and d.meta_description is None:
                d.meta_description = content
            elif name == "viewport" and d.viewport is None:
                d.viewport = content
            elif name == "robots" and d.robots_meta is None:
                d.robots_meta = content.lower()
            if prop.startswith("og:") and content:
                d.open_graph.add(prop)
        elif tag == "link":
            if "canonical" in a.get("rel", "").lower().split() and d.canonical is None:
                d.canonical = a.get("href", "").strip() or None
        elif tag == "img":
            d.images += 1
            if not a.get("alt", "").strip():
                d.images_missing_alt += 1
        elif tag == "a":
            href = a.get("href", "").strip()
            if href:
                d.links.append(href)
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._ld_json, self._buf = True, []

    def handle_data(self, data: str) -> None:
        if self._capture or self._ld_json:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._ld_json and tag == "script":
            self._ld_json = False
            try:
                if json.loads("".join(self._buf)):
                    self.data.has_structured_data = True
            except ValueError:
                pass
        elif self._capture == tag:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                if self.data.title is None:
                    self.data.title = text
            elif text:
                self.data.headings.append(text)
            self._capture = None


def parse_page(html: str) -> PageData:
    extractor = _Extractor()
    extractor.feed(html)
    extractor.close()
    return extractor.data
