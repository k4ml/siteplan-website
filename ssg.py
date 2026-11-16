#!/usr/bin/env python3
# /// script
# dependencies = [
#     "PyYAML>=6.0",
#     "markdown>=3.0",
#     "python-frontmatter>=1.0",
#     "python-dateutil>=2.8",
#     "python-liquid>=1.9,<2",
# ]
# ///
"""
UrusRumah static site generator — a small, Jekyll-compatible SSG.

Usage:
    uv run ssg.py [source_dir] [output_dir]

Supported Jekyll-ish features:
    _config.yml, _posts/*.md, root *.md / *.html pages, _layouts, _includes,
    collections, Liquid templates (python-liquid), sass/scss with front matter,
    sitemap.xml, feed.xml and robots.txt generation.
"""

import argparse
import html
import json
import re
import shutil
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import frontmatter
    import liquid
    import markdown
    import yaml
    from dateutil import parser as dateutil_parser
except ImportError:
    print("Error: dependencies missing. Run: uv run ssg.py")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MALAY_MONTHS = {
    "January": "Januari",
    "February": "Februari",
    "March": "Mac",
    "April": "April",
    "May": "Mei",
    "June": "Jun",
    "July": "Julai",
    "August": "Ogos",
    "September": "September",
    "October": "Oktober",
    "November": "November",
    "December": "Disember",
}

MALAY_MONTHS_SHORT = {
    "Jan": "Jan",
    "Feb": "Feb",
    "Mar": "Mac",
    "Apr": "Apr",
    "May": "Mei",
    "Jun": "Jun",
    "Jul": "Jul",
    "Aug": "Ogos",
    "Sep": "Sep",
    "Oct": "Okt",
    "Nov": "Nov",
    "Dec": "Dis",
}

MALAY_DAYS = {
    "Monday": "Isnin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Khamis",
    "Friday": "Jumaat",
    "Saturday": "Sabtu",
    "Sunday": "Ahad",
}


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (list, tuple, dict)):
        return str(value)
    return str(value)


def to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif not value:
        return None
    else:
        try:
            parsed = dateutil_parser.parse(str(value), dayfirst=True)
        except (ValueError, OverflowError):
            return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def localize_date(text: str) -> str:
    for english, malay in MALAY_MONTHS.items():
        text = re.sub(rf"\b{english}\b", malay, text)
    for english, malay in MALAY_MONTHS_SHORT.items():
        text = re.sub(rf"\b{english}\b", malay, text)
    for english, malay in MALAY_DAYS.items():
        text = re.sub(rf"\b{english}\b", malay, text)
    return text


def strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", to_text(value))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def read_text(path: Path) -> str:
    """Read a source file, stripping a UTF-8 BOM that would break front matter."""
    return path.read_text(encoding="utf-8-sig")


def output_path(url: str) -> str:
    """Return the file a canonical URL should be written to."""
    if url.endswith("/"):
        return url + "index.html"
    if "." not in Path(url).name:
        return url + "/index.html"
    return url


def liquid_date(value: Any, fmt: str = "%Y-%m-%d") -> str:
    parsed = to_datetime(value)
    if not parsed:
        return ""
    try:
        return localize_date(parsed.strftime(to_text(fmt)))
    except ValueError:
        return ""


def liquid_truncate(value: Any, count: Any = 100) -> str:
    text = to_text(value)
    limit = int(count)
    return text[:limit] + ("…" if len(text) > limit else "")


def liquid_truncatewords(value: Any, count: Any = 30) -> str:
    words = strip_html(value).split()
    limit = int(count)
    return " ".join(words[:limit]) + ("…" if len(words) > limit else "")


def build_engine(source_dir: Path) -> liquid.Environment:
    """Build the Liquid environment; includes resolve against _includes."""
    env = liquid.Environment(
        loader=liquid.FileSystemLoader(source_dir / "_includes"),
    )
    env.add_filter("clean_url", lambda url: to_text(url).replace("/index.html", "/"))
    env.add_filter("date", liquid_date)
    env.add_filter("truncate", liquid_truncate)
    env.add_filter("truncatewords", liquid_truncatewords)
    return env


# ---------------------------------------------------------------------------
# Site generator
# ---------------------------------------------------------------------------


class JekyllSSG:
    def __init__(self, source_dir: str = ".", output_dir: str = "_site"):
        self.source_dir = Path(source_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.config = self.load_config()
        self.posts: List[Dict[str, Any]] = []
        self.pages: List[Dict[str, Any]] = []
        self.collections: Dict[str, List[Dict[str, Any]]] = {}
        self.category_pages: List[Dict[str, Any]] = []
        self.engine = build_engine(self.source_dir)
        self._written: Dict[str, str] = {}
        self.site_jsonld = self.build_site_jsonld()

    # -- config / content --------------------------------------------------
    def load_config(self) -> Dict[str, Any]:
        config_file = self.source_dir / "_config.yml"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        return {}

    @staticmethod
    def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        try:
            document = frontmatter.loads(content)
        except yaml.YAMLError as error:
            raise SystemExit(f"Invalid front matter: {error}")
        metadata = document.metadata
        return (metadata if isinstance(metadata, dict) else {}), document.content

    def process_markdown(self, file_path: Path) -> Dict[str, Any]:
        content = read_text(file_path)
        frontmatter, body = self.parse_frontmatter(content)
        converter = markdown.Markdown(
            extensions=["toc", "fenced_code", "tables", "sane_lists", "attr_list"],
            extension_configs={"toc": {"toc_depth": "2-3"}},
        )
        rendered = converter.convert(body)
        return {
            "frontmatter": frontmatter,
            "content": rendered,
            "toc": getattr(converter, "toc", ""),
            "toc_tokens": getattr(converter, "toc_tokens", []),
        }

    def process_html(self, file_path: Path) -> Dict[str, Any]:
        content = read_text(file_path)
        frontmatter, body = self.parse_frontmatter(content)
        return {"frontmatter": frontmatter, "content": body}

    def category_map(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for category in self.config.get("categories", []):
            if isinstance(category, dict) and category.get("slug"):
                result[str(category["slug"])] = category
        return result

    def process_posts(self):
        posts_dir = self.source_dir / "_posts"
        if not posts_dir.exists():
            return
        categories = self.category_map()

        for file_path in sorted(posts_dir.glob("*.md")):
            data = self.process_markdown(file_path)
            frontmatter: Dict[str, Any] = data["frontmatter"]

            date_value = frontmatter.get("date")
            parsed_date = to_datetime(date_value)
            if not parsed_date:
                match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})-", file_path.name)
                if match:
                    year, month, day = (int(part) for part in match.groups())
                    try:
                        parsed_date = datetime(year, month, day)
                    except ValueError:
                        parsed_date = None
            if not parsed_date:
                raise SystemExit(
                    f"{file_path.name}: missing or unparseable date. Add a date to "
                    "the front matter or the filename before building."
                )
            frontmatter["date"] = parsed_date

            slug = to_text(frontmatter.get("slug")).strip()
            if not slug:
                slug = re.sub(r"^\d{4}-\d{1,2}-\d{1,2}-", "", file_path.stem)

            category_slug = to_text(frontmatter.get("category", "umum")) or "umum"
            category = categories.get(category_slug, {})
            description = to_text(frontmatter.get("description")).strip()
            if not description:
                description = strip_html(data["content"])[:180]

            words = len(strip_html(data["content"]).split())
            reading_time = max(1, round(words / 200))

            post = dict(frontmatter)
            post.update(
                {
                    "filename": file_path.stem,
                    "slug": slug,
                    "url": self.generate_permalink(frontmatter, file_path, slug),
                    "content": data["content"],
                    "toc": data["toc"],
                    "toc_tokens": data["toc_tokens"],
                    "description": description,
                    "excerpt": description,
                    "category": category_slug,
                    "category_name": to_text(frontmatter.get("category_name"))
                    or to_text(category.get("name"))
                    or category_slug.replace("-", " ").title(),
                    "category_url": f"/kategori/{category_slug}/",
                    "image": to_text(frontmatter.get("image"))
                    or to_text(category.get("image"))
                    or "/assets/img/og-default.png",
                    "author": to_text(frontmatter.get("author"))
                    or to_text(self.config.get("author"))
                    or to_text(self.config.get("name")),
                    "reading_time": reading_time,
                    "date_iso": parsed_date.strftime("%Y-%m-%d"),
                }
            )
            self.posts.append(post)

        self.posts.sort(key=lambda item: item.get("date", datetime.min), reverse=True)

    def process_pages(self):
        processed_stems = set()
        excluded = {to_text(item) for item in self.config.get("exclude", [])}

        for file_path in sorted(self.source_dir.glob("*.html")):
            if file_path.name.startswith("_") or file_path.name in excluded:
                continue
            page_data = self.process_html(file_path)
            frontmatter = page_data["frontmatter"]
            url = self.page_url(frontmatter, file_path.stem)
            page = self.make_page(file_path.stem, url, page_data, frontmatter)
            self.pages.append(page)
            processed_stems.add(file_path.stem)

        for file_path in sorted(self.source_dir.glob("*.md")):
            if (
                file_path.name.startswith("_")
                or file_path.name in excluded
                or file_path.stem in processed_stems
            ):
                continue
            page_data = self.process_markdown(file_path)
            frontmatter = page_data["frontmatter"]
            url = self.page_url(frontmatter, file_path.stem)
            page = self.make_page(file_path.stem, url, page_data, frontmatter)
            self.pages.append(page)
            processed_stems.add(file_path.stem)

    @staticmethod
    def page_url(frontmatter: Dict[str, Any], stem: str) -> str:
        if "permalink" in frontmatter:
            url = to_text(frontmatter["permalink"])
            return output_path(url if url.startswith("/") else "/" + url)
        if stem == "index":
            return "/index.html"
        return f"/{stem}/index.html"

    def make_page(
        self,
        filename: str,
        url: str,
        page_data: Dict[str, Any],
        frontmatter: Dict[str, Any],
    ) -> Dict[str, Any]:
        page = dict(frontmatter)
        page.update(
            {
                "filename": filename,
                "url": url,
                "content": page_data["content"],
                "toc": page_data.get("toc", ""),
                "description": to_text(frontmatter.get("description"))
                or to_text(self.config.get("description")),
                "image": to_text(frontmatter.get("image"))
                or "/assets/img/og-default.png",
                "author": to_text(frontmatter.get("author"))
                or to_text(self.config.get("author")),
            }
        )
        return page

    def process_collections(self):
        for collection_name, collection_config in self.config.get(
            "collections", {}
        ).items():
            if not isinstance(collection_config, dict):
                collection_config = {}
            collection_dir = self.source_dir / f"_{collection_name}"
            if not collection_dir.exists():
                continue
            self.collections[collection_name] = []
            for file_path in sorted(collection_dir.glob("*.md")):
                data = self.process_markdown(file_path)
                frontmatter = data["frontmatter"]
                item = dict(frontmatter)
                item.update(
                    {
                        "filename": file_path.stem,
                        "url": f"/{collection_name}/{file_path.stem}.html",
                        "content": data["content"],
                        "description": to_text(frontmatter.get("description"))
                        or strip_html(data["content"])[:180],
                    }
                )
                self.collections[collection_name].append(item)
            self.collections[collection_name].sort(
                key=lambda item: to_datetime(item.get("date")) or datetime.min,
                reverse=True,
            )

    # -- URLs --------------------------------------------------------------
    def generate_permalink(
        self, frontmatter: Dict[str, Any], file_path: Path, slug: str
    ) -> str:
        style = to_text(self.config.get("permalink", "/:category/:title/"))
        parsed_date = to_datetime(frontmatter.get("date"))
        if not parsed_date:
            raise SystemExit(
                f"{file_path.name}: cannot build a permalink without a date."
            )
        category = to_text(frontmatter.get("category", "")).strip()
        url = style
        url = url.replace(":title", slug)
        url = url.replace(":slug", slug)
        url = url.replace(":category", category)
        url = url.replace(":categories", category)
        url = url.replace(":year", parsed_date.strftime("%Y"))
        url = url.replace(":month", parsed_date.strftime("%m"))
        url = url.replace(":day", parsed_date.strftime("%d"))
        url = re.sub(r"/+", "/", url)
        if not url.startswith("/"):
            url = "/" + url
        return output_path(url)

    def clean_url(self, url: str) -> str:
        url = url.replace("/index.html", "/")
        if url != "/" and not url.endswith("/") and "." not in Path(url).name:
            url += "/"
        return url

    def absolute_url(self, path: str) -> str:
        base = to_text(self.config.get("url", "")).rstrip("/")
        return base + self.clean_url(path)

    def absolute_asset(self, path: str) -> str:
        path = to_text(path)
        if path.startswith(("http://", "https://")):
            return path
        base = to_text(self.config.get("url", "")).rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def resolve_og_image(self, page: Dict[str, Any]) -> str:
        explicit = to_text(page.get("og_image")).strip()
        if explicit:
            return self.absolute_asset(explicit)
        image = to_text(page.get("image")).strip()
        if image.endswith(".svg"):
            # Social networks do not render SVG previews. Look for a matching
            # PNG (cat-dapur.svg -> og-dapur.png or cat-dapur.png).
            stem = Path(image).stem
            candidates = [image[:-4] + ".png", f"/assets/img/og-{stem.removeprefix('cat-')}.png"]
            for candidate in candidates:
                if (self.source_dir / candidate.lstrip("/")).exists():
                    return self.absolute_asset(candidate)
            return self.absolute_asset("/assets/img/og-default.png")
        if image:
            return self.absolute_asset(image)
        return self.absolute_asset("/assets/img/og-default.png")

    # -- categories / related ---------------------------------------------
    def enrich_site(self):
        counts: Dict[str, int] = {}
        for post in self.posts:
            counts[post.get("category", "")] = counts.get(post.get("category", ""), 0) + 1

        for category in self.config.get("categories", []):
            if isinstance(category, dict):
                category["count"] = counts.get(str(category.get("slug")), 0)

        for post in self.posts:
            for product in post.get("products", []) or []:
                if "example.com/aff" in str(product.get("url", "")):
                    raise SystemExit(
                        "Placeholder affiliate URL found in "
                        f"{post.get('slug')} ({product.get('name')}). "
                        "Replace it before building."
                    )

            related = [
                candidate
                for candidate in self.posts
                if candidate is not post
                and candidate.get("category") == post.get("category")
            ][:3]
            if len(related) < 3:
                for candidate in self.posts:
                    if candidate is not post and candidate not in related:
                        related.append(candidate)
                    if len(related) >= 3:
                        break
            post["related"] = related

    def build_category_pages(self):
        categories = [
            item
            for item in self.config.get("categories", [])
            if isinstance(item, dict) and item.get("slug")
        ]
        for category in categories:
            slug = to_text(category.get("slug"))
            posts = [
                post for post in self.posts if post.get("category") == slug
            ]
            if not posts:
                continue
            page = {
                "title": to_text(category.get("name")),
                "description": to_text(category.get("description")),
                "url": f"/kategori/{slug}/index.html",
                "layout": "category",
                "content": "",
                "category": category,
                "posts": posts,
                "image": to_text(category.get("image"))
                or "/assets/img/og-default.png",
            }
            self.category_pages.append(page)

    # -- JSON-LD -----------------------------------------------------------
    def build_site_jsonld(self) -> str:
        name = to_text(self.config.get("name"))
        url = to_text(self.config.get("url")).rstrip("/")
        data = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": f"{url}/#organization",
                    "name": name,
                    "url": f"{url}/",
                    "logo": f"{url}/assets/img/logo.png",
                },
                {
                    "@type": "WebSite",
                    "@id": f"{url}/#website",
                    "name": name,
                    "url": f"{url}/",
                    "description": to_text(self.config.get("description")),
                    "publisher": {"@id": f"{url}/#organization"},
                    "inLanguage": to_text(self.config.get("lang", "ms")),
                },
            ],
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def build_page_jsonld(self, page: Dict[str, Any]) -> str:
        url = self.absolute_url(to_text(page.get("url")))
        name = to_text(self.config.get("name"))
        site_url = to_text(self.config.get("url")).rstrip("/")
        graph: List[Dict[str, Any]] = []

        if page.get("date"):
            graph.append(
                {
                    "@type": "Article",
                    "headline": to_text(page.get("title")),
                    "description": to_text(page.get("description")),
                    "datePublished": to_text(page.get("date_iso")),
                    "dateModified": to_text(
                        page.get("updated_iso") or page.get("date_iso")
                    ),
                    "author": {"@type": "Organization", "name": name},
                    "publisher": {"@id": f"{site_url}/#organization"},
                    "mainEntityOfPage": {"@type": "WebPage", "@id": url},
                    "image": page.get("og_image_absolute")
                    or self.absolute_asset(to_text(page.get("image"))),
                    "inLanguage": to_text(self.config.get("lang", "ms")),
                }
            )
        else:
            graph.append(
                {
                    "@type": "WebPage",
                    "name": to_text(page.get("title") or name),
                    "description": to_text(page.get("description")),
                    "url": url,
                    "isPartOf": {"@id": f"{site_url}/#website"},
                }
            )

        if page.get("faq"):
            graph.append(
                {
                    "@type": "FAQPage",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": to_text(item.get("q")),
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": strip_html(item.get("a")),
                            },
                        }
                        for item in page["faq"]
                        if isinstance(item, dict)
                    ],
                }
            )

        breadcrumbs = [
            {"@type": "ListItem", "position": 1, "name": "Utama", "item": f"{site_url}/"}
        ]
        position = 2
        if page.get("category_name"):
            breadcrumbs.append(
                {
                    "@type": "ListItem",
                    "position": position,
                    "name": to_text(page.get("category_name")),
                    "item": self.absolute_url(to_text(page.get("category_url"))),
                }
            )
            position += 1
        if page.get("title"):
            breadcrumbs.append(
                {
                    "@type": "ListItem",
                    "position": position,
                    "name": to_text(page.get("title")),
                    "item": url,
                }
            )
        graph.append({"@type": "BreadcrumbList", "itemListElement": breadcrumbs})

        data = {
            "@context": "https://schema.org",
            "@graph": graph,
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    # -- rendering ---------------------------------------------------------
    def render_page(self, page_data: Dict[str, Any]) -> str:
        page_data.setdefault("url", "/")
        page_data["canonical"] = self.absolute_url(to_text(page_data["url"]))
        page_data["og_type"] = "article" if page_data.get("date") else "website"
        page_data["image_absolute"] = self.absolute_asset(
            to_text(page_data.get("image") or "/assets/img/og-default.png")
        )
        page_data["og_image_absolute"] = self.resolve_og_image(page_data)
        page_data["jsonld"] = self.build_page_jsonld(page_data)

        site_data = dict(self.config)
        site_data["posts"] = self.posts
        site_data["pages"] = self.pages
        site_data["categories"] = self.config.get("categories", [])
        site_data["jsonld"] = self.site_jsonld

        context: Dict[str, Any] = {
            "page": page_data,
            "site": site_data,
            "content": page_data.get("content", ""),
        }

        content = self.engine.from_string(page_data.get("content", "")).render(context)

        layout = page_data.get("layout", "default")
        seen = set()
        while layout and layout not in seen:
            seen.add(layout)
            layout_path = self.source_dir / "_layouts" / f"{layout}.html"
            if not layout_path.exists():
                break
            raw_layout = read_text(layout_path)
            layout_frontmatter, layout_body = self.parse_frontmatter(raw_layout)
            if layout_frontmatter.get("body_class") and not page_data.get("body_class"):
                page_data["body_class"] = layout_frontmatter["body_class"]
            context["content"] = content
            content = self.engine.from_string(layout_body).render(context)
            layout = layout_frontmatter.get("layout")

        return content

    def write_output(self, relative_url: str, content: str, source: str = "") -> Path:
        if relative_url in self._written:
            raise SystemExit(
                f"Duplicate URL {self.clean_url(relative_url)}: written by "
                f"{self._written[relative_url]} and {source or 'another page'}. "
                "Give them distinct permalinks or slugs."
            )
        self._written[relative_url] = source or "unknown"
        target = Path(self.output_dir) / relative_url.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    # -- generation --------------------------------------------------------
    def generate_site(self):
        print(f"Building site from {self.source_dir} to {self.output_dir}")

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True)

        self.process_posts()
        self.process_pages()
        self.process_collections()
        self.enrich_site()
        self.build_category_pages()

        self.process_scss_files()
        self.copy_static_files()
        self.copy_public_files()

        for post in self.posts:
            self.write_output(post["url"], self.render_page(post), post.get("filename", ""))
            print(f"Generated: {post['url']}")

        for page in self.pages:
            self.write_output(page["url"], self.render_page(page), page.get("filename", ""))
            print(f"Generated: {page['url']}")

        for category_page in self.category_pages:
            self.write_output(
                category_page["url"],
                self.render_page(category_page),
                f"kategori/{category_page['url']}",
            )
            print(f"Generated: {category_page['url']}")

        for collection_name, items in self.collections.items():
            for item in items:
                self.write_output(
                    item["url"], self.render_page(item), item.get("filename", "")
                )
                print(f"Generated: {item['url']}")

        self.generate_sitemap()
        self.generate_feed()
        self.generate_robots()

        print(f"Site generated successfully in {self.output_dir}")

    def copy_static_files(self):
        static_extensions = {
            ".css",
            ".js",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".gif",
            ".svg",
            ".ico",
            ".txt",
            ".xml",
            ".json",
            ".webmanifest",
            ".woff",
            ".woff2",
            ".pdf",
        }
        for item in self.source_dir.rglob("*"):
            if not item.is_file() or item.suffix.lower() not in static_extensions:
                continue
            relative = item.relative_to(self.source_dir)
            if relative.as_posix() in {"requirements.txt", "LICENSE", "README.md"}:
                continue
            if any(part.startswith(("_", ".")) for part in relative.parts):
                continue
            if relative.parts and relative.parts[0] in ("public", "_site", "node_modules"):
                continue
            output_path = self.output_dir / relative
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, output_path)

    def copy_public_files(self):
        public_dir = self.source_dir / "public"
        if not public_dir.exists():
            return
        for item in public_dir.rglob("*"):
            if item.is_file():
                relative = item.relative_to(public_dir)
                output_path = self.output_dir / relative
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, output_path)

    def generate_sitemap(self):
        base = to_text(self.config.get("url", "")).rstrip("/")
        entries: List[Tuple[str, Optional[str]]] = [("/", None)]

        for page in self.pages:
            if page.get("sitemap") is False or page["url"] == "/404.html":
                continue
            entries.append((self.clean_url(page["url"]), None))
        for post in self.posts:
            entries.append(
                (self.clean_url(post["url"]), post.get("date_iso"))
            )
        for category_page in self.category_pages:
            entries.append((self.clean_url(category_page["url"]), None))

        seen = set()
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for path, lastmod in entries:
            if path in seen:
                continue
            seen.add(path)
            lines.append("  <url>")
            lines.append(f"    <loc>{html.escape(base + path)}</loc>")
            if lastmod:
                lines.append(f"    <lastmod>{lastmod}</lastmod>")
            lines.append("  </url>")
        lines.append("</urlset>")
        self.write_output("/sitemap.xml", "\n".join(lines))

    def generate_feed(self):
        base = to_text(self.config.get("url", "")).rstrip("/")
        title = to_text(self.config.get("name"))
        description = to_text(self.config.get("description"))
        items = []
        for post in self.posts[:20]:
            link = base + self.clean_url(post["url"])
            published = post.get("date")
            pub_date = (
                published.strftime("%a, %d %b %Y 00:00:00 +0000")
                if isinstance(published, datetime)
                else ""
            )
            items.append(
                "    <item>\n"
                f"      <title>{html.escape(to_text(post.get('title')))}</title>\n"
                f"      <link>{html.escape(link)}</link>\n"
                f"      <guid isPermaLink=\"true\">{html.escape(link)}</guid>\n"
                f"      <pubDate>{pub_date}</pubDate>\n"
                f"      <description>{html.escape(to_text(post.get('description')))}</description>\n"
                "    </item>"
            )
        feed = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>{html.escape(title)}</title>\n"
            f"    <link>{html.escape(base)}/</link>\n"
            f"    <description>{html.escape(description)}</description>\n"
            f"    <language>{to_text(self.config.get('lang', 'ms'))}</language>\n"
            f'    <atom:link href="{html.escape(base)}/feed.xml" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(items)
            + "\n  </channel>\n</rss>\n"
        )
        self.write_output("/feed.xml", feed)

    def generate_robots(self):
        base = to_text(self.config.get("url", "")).rstrip("/")
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )
        self.write_output("/robots.txt", content)

    # -- SCSS (kept for Jekyll compatibility) ------------------------------
    def process_scss_files(self):
        for scss_file in self.source_dir.glob("*.scss"):
            content = scss_file.read_text(encoding="utf-8")
            if not content.startswith("---\n"):
                continue
            _, scss_content = self.parse_frontmatter(content)
            css_content = self.process_scss_imports(scss_content.lstrip())
            output_path = self.output_dir / scss_file.with_suffix(".css").name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(css_content, encoding="utf-8")
            print(f"Generated: {output_path}")

    def process_scss_imports(self, scss_content: str) -> str:
        variables: Dict[str, str] = {}

        def collect_variables(content: str):
            for match in re.finditer(r"\$([a-zA-Z0-9_-]+)\s*:\s*([^;]+);", content):
                variables[match.group(1)] = match.group(2).strip()

        def replace_import(match):
            import_file = match.group(1).strip("\"'")
            sass_path = self.source_dir / "_sass" / f"_{import_file}.scss"
            if sass_path.exists():
                imported = sass_path.read_text(encoding="utf-8")
                collect_variables(imported)
                return imported
            return f"/* Import not found: {import_file} */"

        scss_content = re.sub(
            r'@import\s+["\']([^"\']+)["\'];?', replace_import, scss_content
        )
        collect_variables(scss_content)

        for _ in range(10):
            changed = False
            for name, value in list(variables.items()):
                for reference in re.findall(r"\$([a-zA-Z0-9_-]+)", value):
                    if reference in variables and reference != name:
                        variables[name] = value.replace(
                            f"${reference}", variables[reference]
                        )
                        if variables[name] != value:
                            changed = True
            if not changed:
                break

        scss_content = re.sub(
            r"\$([a-zA-Z0-9_-]+)",
            lambda match: variables.get(match.group(1), match.group(0)),
            scss_content,
        )
        scss_content = re.sub(
            r"^\s*\$[a-zA-Z0-9_-]+\s*:[^;]+;\s*$", "", scss_content, flags=re.MULTILINE
        )
        scss_content = re.sub(r"//.*$", "", scss_content, flags=re.MULTILINE)
        return scss_content


def main():
    parser = argparse.ArgumentParser(
        description="UrusRumah — a small Jekyll-compatible static site generator"
    )
    parser.add_argument(
        "source", nargs="?", default=".", help="Source directory (default: current)"
    )
    parser.add_argument(
        "output", nargs="?", default="_site", help="Output directory (default: _site)"
    )

    args = parser.parse_args()
    generator = JekyllSSG(args.source, args.output)
    generator.generate_site()


if __name__ == "__main__":
    main()
