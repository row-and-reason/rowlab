"""Check built branding metadata: python3 brand/check.py after building all sites."""

import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attrs.get("name", attrs.get("property"))
            self.values.setdefault(key, []).append(attrs.get("content", ""))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.values.setdefault("canonical", []).append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.values.setdefault("title", []).append(data)


for directory, host in [
    ("site/www/dist", "rowlab.dev"),
    ("site/docs/dist", "docs.rowlab.dev"),
    ("web/out", "app.rowlab.dev"),
]:
    output = ROOT / directory
    pages = list(output.rglob("*.html"))
    assert pages, f"Build {directory} first"
    checked = 0
    for page in pages:
        if "404" in page.parts or page.name == "404.html" or "_not-found" in page.parts:
            continue
        head = Head()
        head.feed(page.read_text().split("</head>")[0])
        for key in [
            "title",
            "description",
            "canonical",
            "og:title",
            "og:description",
            "og:url",
            "og:image",
            "twitter:card",
            "twitter:title",
            "twitter:description",
            "twitter:image",
        ]:
            values = head.values.get(key, [])
            assert len(values) == 1 and values[0], (page, key, values)
        assert head.values["twitter:card"] == ["summary_large_image"], page
        for key in ["canonical", "og:url", "og:image", "twitter:image"]:
            url = urlparse(head.values[key][0])
            assert url.scheme == "https" and url.hostname == host, (page, key, url)
            if "image" in key:
                image = output / url.path.lstrip("/")
                data = image.read_bytes()
                assert data[:8] == b"\x89PNG\r\n\x1a\n", image
                assert struct.unpack(">II", data[16:24]) == (1200, 630), image
        checked += 1
    for icon in ["favicon.svg", "favicon.ico", "apple-touch-icon.png"]:
        assert (output / icon).stat().st_size > 0, (directory, icon)
    print(f"{directory}: {checked} pages passed; preview images and icons exist")
