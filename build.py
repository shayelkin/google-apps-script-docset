# /// script
# dependencies = ["beautifulsoup4", "lxml", "pillow"]
# ///
"""Build GoogleAppsScript.docset from the pages cached by fetch.py."""

import html
import plistlib
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from PIL import Image, ImageDraw, ImageFont

BASE = "https://developers.google.com"
ROOT = "/apps-script/reference"
HERE = Path(__file__).parent
CACHE = HERE / "cache"
DOCSET = HERE / "GoogleAppsScript.docset"
DOCS = DOCSET / "Contents/Resources/Documents"

STRIP_SELECTORS = [
    "devsite-feedback",
    "devsite-thumb-rating",
    "devsite-toc",
    "devsite-code-buttons",
    "devsite-actions",
    ".devsite-article-meta",
    ".devsite-floating-action-buttons",
    ".devsite-page-title-meta",
    "script",
    "style",
    "button",
]

CSS = """
:root { color-scheme: light dark; --fg:#202124; --bg:#fff; --mut:#5f6368; --bd:#dadce0; --code:#f1f3f4; --link:#1a73e8; }
@media (prefers-color-scheme: dark) { :root { --fg:#e8eaed; --bg:#202124; --mut:#9aa0a6; --bd:#3c4043; --code:#2d2e31; --link:#8ab4f8; } }
body { font: 15px/1.5 -apple-system, "Helvetica Neue", sans-serif; color: var(--fg); background: var(--bg); margin: 0; padding: 1rem 1.5rem 3rem; max-width: 62rem; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
h1 { font-size: 1.8rem; margin: .5rem 0 1rem; } h2 { font-size: 1.35rem; border-bottom: 1px solid var(--bd); padding-bottom: .2rem; margin-top: 2rem; } h3 { font-size: 1.1rem; }
code, pre { font: 13px/1.45 ui-monospace, Menlo, monospace; background: var(--code); border-radius: 4px; }
code { padding: .1em .3em; } pre { padding: .7rem .9rem; overflow-x: auto; } pre code { padding: 0; background: none; }
table { border-collapse: collapse; width: 100%; margin: .6rem 0 1rem; } th, td { border: 1px solid var(--bd); padding: .35rem .6rem; text-align: left; vertical-align: top; }
th { background: var(--code); }
div.doc { border-top: 1px solid var(--bd); margin-top: 1.5rem; padding-top: .3rem; }
.expandable > *, .expandable { display: block !important; }
.devsite-syntax-c, .devsite-syntax-c1, .devsite-syntax-cm { color: #5f6368; font-style: italic; }
.devsite-syntax-s, .devsite-syntax-s1, .devsite-syntax-s2, .devsite-syntax-sb, .devsite-syntax-si { color: #0b8043; }
.devsite-syntax-k, .devsite-syntax-kd, .devsite-syntax-kr, .devsite-syntax-ow { color: #a142f4; }
.devsite-syntax-m, .devsite-syntax-mi, .devsite-syntax-mf, .devsite-syntax-kc { color: #d93025; }
.devsite-syntax-nb, .devsite-syntax-nc { color: #1a73e8; }
nav.crumbs { color: var(--mut); font-size: .85rem; margin-bottom: .5rem; }
footer { color: var(--mut); font-size: .8rem; margin-top: 3rem; border-top: 1px solid var(--bd); padding-top: .5rem; }
"""


def page_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for f in sorted(CACHE.glob("*.html")):
        if f.name == "_index.html":
            continue
        out.append((f.stem.replace("__", "/"), f))
    return out


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def rewrite_links(body: Tag, page_url: str, known: set[str], depth: int) -> None:
    up = "../" * depth
    for a in body.find_all("a", href=True):
        href: str = a["href"]
        if href.startswith("#"):
            continue
        full = urljoin(page_url, href)
        parts = urlsplit(full)
        key = parts.path.removeprefix(ROOT + "/").rstrip("/")
        if (
            parts.netloc == "developers.google.com"
            and parts.path.startswith(ROOT + "/")
            and key in known
        ):
            a["href"] = f"{up}{key}.html" + (
                f"#{parts.fragment}" if parts.fragment else ""
            )
            continue
        a["href"] = full
    for img in body.find_all("img", src=True):
        img["src"] = urljoin(page_url, img["src"])


def clean(
    soup: BeautifulSoup, title: str, page_url: str, known: set[str], depth: int
) -> tuple[Tag, BeautifulSoup]:
    article = soup.find("article")
    for sel in STRIP_SELECTORS:
        for t in article.select(sel):
            t.decompose()
    summary = article.find("h2", id="key-takeaways-panel-title")
    if summary is not None:
        container = summary.find_parent(
            lambda t: t.name and t.name.startswith("devsite-")
        )
        (container or summary).decompose()
    for t in article.find_all("devsite-code"):
        t.unwrap()
    for t in article.find_all(True):
        for attr in ("tabindex", "is-upgraded"):
            t.attrs.pop(attr, None)
    h1 = article.find("h1")
    h1.clear()
    h1.string = title
    body = article.find(class_="devsite-article-body")
    wrapper = BeautifulSoup("<article></article>", "lxml").find("article")
    wrapper.append(h1.extract())
    wrapper.append(body.extract())
    rewrite_links(wrapper, page_url, known, depth)
    return wrapper, soup


def wrap(title: str, depth: int, content: Tag | str, online_url: str) -> str:
    up = "../" * depth
    return (
        "<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
        f"<title>{html.escape(title)}</title>"
        f'<link rel=stylesheet href="{up}style.css"></head><body>{content}'
        f'<footer>Source: <a href="{online_url}">{html.escape(online_url)}</a>. '
        "Content by Google, licensed under CC BY 4.0 (code samples: Apache 2.0).</footer>"
        "</body></html>"
    )


def make_icon(dest: Path) -> None:
    size = 128
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, size - 4, size - 4), radius=26, fill=(66, 133, 244, 255))
    font = ImageFont.load_default(size=64)
    d.text((size / 2, size / 2), "{ }", font=font, fill="white", anchor="mm")
    img.resize((32, 32), Image.LANCZOS).save(dest / "icon@2x.png")
    img.resize((16, 16), Image.LANCZOS).save(dest / "icon.png")


def main() -> int:
    files = page_files()
    known = {key for key, _ in files}
    if DOCSET.exists():
        shutil.rmtree(DOCSET)
    DOCS.mkdir(parents=True)
    (DOCS / "style.css").write_text(CSS)
    entries: set[tuple[str, str, str]] = set()
    services: list[tuple[str, str]] = []

    def add(name: str, kind: str, path: str) -> None:
        entries.add((name, kind, path))

    for key, f in files:
        soup = BeautifulSoup(f.read_bytes(), "lxml")
        title = squash(soup.title.get_text().split("|")[0])
        depth = key.count("/")
        page_url = f"{BASE}{ROOT}/{key}"
        rel = f"{key}.html"
        is_service = depth == 0
        if is_service:
            kind, name = "Service", title
            services.append((name, rel))
        else:
            prefix, _, name = title.partition(" ")
            if prefix not in ("Class", "Enum", "Interface") or not name:
                raise ValueError(f"unexpected page title {title!r} in {f.name}")
            kind = prefix
        add(name, kind, rel)
        article, _ = clean(soup, title, page_url, known, depth)

        if not is_service:
            for d in article.select("div.doc[id]"):
                h3 = d.find("h3")
                if h3 is None:
                    raise ValueError(f"member without heading in {f.name}: {d['id']}")
                member = f"{name}.{squash(h3.get_text())}"
                anchor = f"//apple_ref/cpp/Method/{quote(member, safe='')}"
                d.insert_before(
                    BeautifulSoup(
                        f'<a name="{anchor}" class="dashAnchor"></a>', "lxml"
                    ).a
                )
                add(member, "Method", f"{rel}#{anchor}")
            for table in article.select("table.members.property"):
                member_kind = "Constant" if kind == "Enum" else "Property"
                for row in table.select("tr")[1:]:
                    cell = row.find("td")
                    member = f"{name}.{squash(cell.get_text())}"
                    anchor = f"//apple_ref/cpp/{member_kind}/{quote(member, safe='')}"
                    cell.insert(
                        0,
                        BeautifulSoup(
                            f'<a name="{anchor}" class="dashAnchor"></a>', "lxml"
                        ).a,
                    )
                    add(member, member_kind, f"{rel}#{anchor}")

        out = DOCS / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(wrap(title, depth, str(article), page_url))

    items = "".join(
        f'<li><a href="{p}">{html.escape(n)}</a></li>' for n, p in sorted(services)
    )
    (DOCS / "index.html").write_text(
        wrap(
            "Apps Script Reference",
            0,
            f"<h1>Apps Script Reference</h1><ul>{items}</ul>",
            BASE + ROOT,
        )
    )

    res = DOCSET / "Contents/Resources"
    db = sqlite3.connect(res / "docSet.dsidx")
    db.executescript(
        "CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);"
        "CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);"
    )
    db.executemany(
        "INSERT INTO searchIndex(name, type, path) VALUES (?,?,?)", sorted(entries)
    )
    db.commit()
    db.close()

    with (DOCSET / "Contents/Info.plist").open("wb") as fh:
        plistlib.dump(
            {
                "CFBundleIdentifier": "appsscript",
                "CFBundleName": "Google Apps Script",
                "DocSetPlatformFamily": "appsscript",
                "isDashDocset": True,
                "dashIndexFilePath": "index.html",
                "DashDocSetFallbackURL": BASE + ROOT + "/",
                "isJavaScriptEnabled": False,
            },
            fh,
        )
    make_icon(DOCSET)
    by_kind: dict[str, int] = {}
    for _, k, _ in entries:
        by_kind[k] = by_kind.get(k, 0) + 1
    print(len(files), "pages;", len(entries), "entries;", dict(sorted(by_kind.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
