# /// script
# dependencies = ["beautifulsoup4", "lxml"]
# ///
"""Download the Apps Script reference pages into ./cache."""

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup

BASE = "https://developers.google.com"
ROOT = "/apps-script/reference"
CACHE = Path(__file__).parent / "cache"


def get(path: str) -> bytes:
    last = ""
    for attempt in range(5):
        r = subprocess.run(
            ["curl", "-sfL", "--compressed", "--max-time", "90", BASE + path],
            capture_output=True,
            check=False,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
        last = f"curl exit {r.returncode}: {r.stderr.decode(errors='replace')}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {path}: {last}")


def cache_name(path: str) -> Path:
    return CACHE / (path.removeprefix(ROOT).strip("/").replace("/", "__") + ".html")


def fetch(path: str) -> str:
    dest = cache_name(path)
    if dest.exists():
        return path
    dest.write_bytes(get(path))
    return path


def page_paths(index_html: bytes) -> list[str]:
    soup = BeautifulSoup(index_html, "lxml")
    paths: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"].split("#")[0]
        if (
            href.startswith(ROOT + "/")
            and href.count("/") == ROOT.count("/") + 1
            and href not in paths
        ):
            paths.append(href)
    return paths


def main() -> int:
    CACHE.mkdir(exist_ok=True)
    index = get(ROOT)
    (CACHE / "_index.html").write_bytes(index)
    services = page_paths(index)
    for s in services:
        fetch(s)
    pages: list[str] = []
    for s in services:
        soup = BeautifulSoup(cache_name(s).read_bytes(), "lxml")
        for a in soup.find("article").find_all("a", href=True):
            href: str = a["href"].split("#")[0]
            if href.startswith(s + "/") and href not in pages:
                pages.append(href)
    with ThreadPoolExecutor(8) as ex:
        for i, _ in enumerate(ex.map(fetch, pages), 1):
            if i % 100 == 0:
                print(f"{i}/{len(pages)}", flush=True)
    print(f"services={len(services)} pages={len(pages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
