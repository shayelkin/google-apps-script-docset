# /// script
# dependencies = ["pytest", "beautifulsoup4", "lxml"]
# ///
import plistlib
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

DOCSET = Path(__file__).parent / "GoogleAppsScript.docset"
RES = DOCSET / "Contents/Resources"
DOCS = RES / "Documents"
VALID_TYPES = {
    "Service",
    "Class",
    "Enum",
    "Interface",
    "Method",
    "Property",
    "Constant",
}


@pytest.fixture(scope="module")
def rows() -> list[tuple[str, str, str]]:
    db = sqlite3.connect(RES / "docSet.dsidx")
    try:
        return db.execute("SELECT name, type, path FROM searchIndex").fetchall()
    finally:
        db.close()


@pytest.fixture(scope="module")
def pages() -> dict[Path, BeautifulSoup]:
    return {p: BeautifulSoup(p.read_text(), "lxml") for p in DOCS.rglob("*.html")}


def test_info_plist_required_keys() -> None:
    info = plistlib.loads((DOCSET / "Contents/Info.plist").read_bytes())
    for key in (
        "CFBundleIdentifier",
        "CFBundleName",
        "DocSetPlatformFamily",
        "isDashDocset",
    ):
        assert key in info, f"Info.plist must define {key}"
    assert info["isDashDocset"] is True, "isDashDocset must be true"
    assert (DOCS / info["dashIndexFilePath"]).is_file(), "dashIndexFilePath must exist"


def test_icons_exist() -> None:
    assert (DOCSET / "icon.png").is_file(), "16x16 icon must exist"
    assert (DOCSET / "icon@2x.png").is_file(), "32x32 icon must exist"


def test_index_types_are_valid(rows: list[tuple[str, str, str]]) -> None:
    assert {t for _, t, _ in rows} <= VALID_TYPES, (
        "all entry types must be known Dash types"
    )


def test_index_has_no_empty_names(rows: list[tuple[str, str, str]]) -> None:
    assert all(n.strip() and not n.endswith(".") for n, _, _ in rows), (
        "names must be non-empty and complete"
    )


def test_index_paths_resolve_to_files_and_anchors(
    rows: list[tuple[str, str, str]], pages: dict[Path, BeautifulSoup]
) -> None:
    bad: list[str] = []
    for name, _, path in rows:
        file, _, frag = path.partition("#")
        target = DOCS / file
        if target not in pages:
            bad.append(f"{name}: missing file {file}")
            continue
        if frag and not pages[target].find("a", attrs={"name": frag}):
            bad.append(f"{name}: missing anchor {frag}")
    assert not bad, f"unresolved index entries: {bad[:5]}"


def test_every_page_is_indexed(
    rows: list[tuple[str, str, str]], pages: dict[Path, BeautifulSoup]
) -> None:
    indexed = {p.partition("#")[0] for _, _, p in rows}
    missing = {str(p.relative_to(DOCS)) for p in pages} - indexed - {"index.html"}
    assert not missing, f"pages without an index entry: {sorted(missing)[:5]}"


def test_internal_links_resolve(pages: dict[Path, BeautifulSoup]) -> None:
    bad: list[str] = []
    resolved = {p.resolve() for p in pages}
    for page, soup in pages.items():
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            parts = urlsplit(href)
            if parts.scheme or href.startswith("#"):
                continue
            target = (page.parent / parts.path).resolve()
            if target not in resolved:
                bad.append(f"{page.name}: {href}")
    assert not bad, f"broken relative links: {bad[:5]}"


def test_pages_are_self_contained(pages: dict[Path, BeautifulSoup]) -> None:
    for page, soup in pages.items():
        assert not soup.find("script"), f"{page.name} must not contain scripts"
        assert not soup.find(re.compile(r"^devsite-")), (
            f"{page.name} must not contain devsite elements"
        )
        assert not soup.find("link", href=re.compile(r"^https?:")), (
            f"{page.name} must not load remote CSS"
        )


def test_known_entries(rows: list[tuple[str, str, str]]) -> None:
    names = {(n, t) for n, t, _ in rows}
    for expected in [
        ("CalendarApp", "Class"),
        ("Calendar Service", "Service"),
        ("Color", "Enum"),
        ("Color.BLUE", "Constant"),
        ("CalendarApp.createAllDayEvent(title, date)", "Method"),
        ("CalendarApp.Color", "Property"),
    ]:
        assert expected in names, f"{expected} should be indexed"


CACHE = Path(__file__).parent / "cache"
CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
APACHE_2 = "https://www.apache.org/licenses/LICENSE-2.0"


def test_source_pages_license_unchanged() -> None:
    files = list(CACHE.glob("*.html"))
    assert files, "cache must contain fetched source pages; run fetch.py first"
    content = re.compile(
        r"content of this page is licensed under the\s+<a href=\""
        + re.escape(CC_BY_4)
        + r"\">Creative Commons Attribution 4\.0 License</a>"
    )
    code = re.compile(
        r"code samples are licensed under the\s+<a href=\""
        + re.escape(APACHE_2)
        + r"\">Apache 2\.0 License</a>"
    )
    bad: list[str] = []
    for f in files:
        text = f.read_text()
        if not content.search(text):
            bad.append(f"{f.name}: content not CC BY 4.0")
        if not code.search(text):
            bad.append(f"{f.name}: code samples not Apache 2.0")
    assert not bad, (
        f"source licensing differs from expected (CC BY 4.0 + Apache 2.0): {bad[:5]}"
    )


def test_docset_pages_carry_attribution(pages: dict[Path, BeautifulSoup]) -> None:
    for page, soup in pages.items():
        footer = soup.find("footer")
        assert footer is not None, f"{page.name} must have a license footer"
        assert "CC BY 4.0" in footer.get_text() and "Apache 2.0" in footer.get_text(), (
            f"{page.name} footer must state both licenses"
        )
