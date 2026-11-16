#!/usr/bin/env python3
"""Validate the generated site in `_site` before it is published.

Checks, using only the standard library so CI needs no extra install:

- every expected page exists
- no placeholder domain leaked into the output
- every internal link resolves to a file, and every fragment to an anchor
- every referenced stylesheet, script and image exists
- ids are unique per page and tags are balanced

Usage:
    python3 scripts/check_site.py [_site]
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

PAGES = [
    "index.html",
    "concept/index.html",
    "architecture/index.html",
    "design/index.html",
    "vision/index.html",
]

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

PLACEHOLDER_DOMAINS = ["siteplan.example"]

# Files the generator emits that are not linked from a page.
UNLINKED_ALLOWED = {"sitemap.xml", "feed.xml", "robots.txt"}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, tuple[int, int]]] = []
        self.errors: list[str] = []
        self.ids: dict[str, int] = {}
        self.links: list[str] = []
        self.assets: list[str] = []
        self.images_without_alt: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids[element_id] = self.ids.get(element_id, 0) + 1

        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag in ("link", "script", "img"):
            ref = values.get("href") or values.get("src")
            if ref:
                self.assets.append(ref)
        if tag == "img" and "alt" not in values:
            self.images_without_alt.append(values.get("src", "<no src>"))

        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}> at {self.getpos()}")
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                unclosed = [name for name, _ in self.stack[index + 1:]]
                self.errors.append(
                    f"unclosed {unclosed} before </{tag}> at {self.getpos()}"
                )
                del self.stack[index:]
                return
        self.errors.append(f"unexpected </{tag}> at {self.getpos()}")


def output_target(path: str) -> str:
    """Map a site path such as /concept/ to the file the server would serve."""
    cleaned = path.strip("/")
    if not cleaned:
        return "index.html"
    if Path(cleaned).suffix:
        return cleaned
    return f"{cleaned}/index.html"


def check_pages(site: Path) -> list[str]:
    problems: list[str] = []

    missing = [page for page in PAGES if not (site / page).is_file()]
    problems.extend(f"missing expected page: {page}" for page in missing)

    parsers: dict[str, PageParser] = {}
    for file_path in sorted(site.rglob("*.html")):
        parser = PageParser()
        parser.feed(file_path.read_text(encoding="utf-8"))
        parsers[file_path.relative_to(site).as_posix()] = parser

    anchors = {name: set(parser.ids) for name, parser in parsers.items()}

    for name, parser in parsers.items():
        for error in parser.errors:
            problems.append(f"{name}: {error}")

        leftover = [tag for tag, _ in parser.stack]
        if leftover:
            problems.append(f"{name}: tags never closed: {leftover}")

        duplicate = [key for key, count in parser.ids.items() if count > 1]
        if duplicate:
            problems.append(f"{name}: duplicate id(s): {duplicate}")

        for source in parser.images_without_alt:
            problems.append(f"{name}: image without alt text: {source}")

        for href in parser.links:
            if href.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            if href.startswith("#"):
                if href[1:] and href[1:] not in parser.ids:
                    problems.append(f"{name}: missing local anchor {href}")
                continue

            target, _, fragment = href.partition("#")
            target_file = output_target(target)
            if not (site / target_file).is_file():
                problems.append(f"{name}: link to missing page {href}")
                continue
            if fragment and fragment not in anchors.get(target_file, set()):
                problems.append(f"{name}: missing anchor {href}")

        for ref in parser.assets:
            if ref.startswith(("http://", "https://", "//", "data:")):
                continue
            if not (site / output_target(ref)).is_file():
                problems.append(f"{name}: missing asset {ref}")

    return problems


def check_placeholders(site: Path) -> list[str]:
    problems: list[str] = []
    suffixes = {".html", ".xml", ".txt", ".css", ".js"}
    for file_path in site.rglob("*"):
        if not file_path.is_file() or file_path.suffix not in suffixes:
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for domain in PLACEHOLDER_DOMAINS:
            if domain in text:
                problems.append(
                    f"{file_path.relative_to(site)}: placeholder domain {domain}"
                )
    return problems


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve()

    if not site.is_dir():
        print(f"error: {site} does not exist; build the site first", file=sys.stderr)
        return 1

    problems = check_pages(site) + check_placeholders(site)

    generated = sorted(
        path.relative_to(site).as_posix() for path in site.rglob("*") if path.is_file()
    )
    print(f"Checked {len(generated)} files in {site}")

    if problems:
        print(f"\n{len(problems)} problem(s) found:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("All checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
