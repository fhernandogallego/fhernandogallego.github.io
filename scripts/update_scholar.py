"""Refresh every publication and metric from a public Google Scholar profile."""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from scholarly import scholarly


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "scholar.json"
HISTORY_FILE = ROOT / "data" / "scholar-history.jsonl"
AUTHOR_ID = os.environ.get("SCHOLAR_AUTHOR_ID", "89e5aoQAAAAJ")
PUBLICATIONS_BLOCK = re.compile(
    r"(?P<start>\s*<!-- scholar-publications:start -->).*?"
    r"(?P<end>\s*<!-- scholar-publications:end -->)",
    re.DOTALL,
)
METRIC_KEYS = (
    "total_citations",
    "citations_5y",
    "hindex",
    "hindex5y",
    "i10index",
    "i10index5y",
    "citations_current_year",
)


def as_int(value: object) -> int:
    """Return Scholar's numeric fields as integers without accepting junk."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_previous() -> dict | None:
    if not DATA_FILE.exists():
        return None
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def author_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(author) for author in value)
    return str(value or "")


def publication_url(item: dict) -> str:
    direct_url = item.get("pub_url") or item.get("eprint_url")
    if direct_url:
        return str(direct_url)
    publication_id = item.get("author_pub_id", "")
    if publication_id:
        return (
            "https://scholar.google.com/citations?view_op=view_citation"
            f"&hl=en&user={quote(AUTHOR_ID)}&citation_for_view={quote(publication_id)}"
        )
    return f"https://scholar.google.com/citations?user={quote(AUTHOR_ID)}"


def fetch_snapshot() -> dict:
    """Download the complete profile and normalize it for the static website."""
    author = scholarly.fill(
        scholarly.search_author_id(AUTHOR_ID),
        sections=["basics", "indices", "counts", "publications"],
    )
    publications = []
    for item in author.get("publications", []):
        bib = item.get("bib", {}) or {}
        title = str(bib.get("title") or "")
        venue = str(bib.get("citation") or bib.get("venue") or "")
        if not venue or title.endswith(("…", "...")):
            try:
                item = scholarly.fill(item)
                bib = item.get("bib", {}) or bib
            except Exception:  # Scholar can throttle individual detail pages.
                pass
        publications.append(
            {
                "title": str(bib.get("title") or title or "Untitled"),
                "authors": author_text(bib.get("author")),
                "year": str(bib.get("pub_year") or ""),
                "venue": str(bib.get("citation") or bib.get("venue") or venue),
                "citations": as_int(item.get("num_citations")),
                "author_pub_id": str(item.get("author_pub_id") or ""),
                "url": publication_url(item),
            }
        )

    now = datetime.now(timezone.utc)
    cites_per_year = author.get("cites_per_year", {}) or {}
    current_year_citations = cites_per_year.get(now.year, cites_per_year.get(str(now.year), 0))
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "Google Scholar",
        "profile": f"https://scholar.google.com/citations?user={AUTHOR_ID}",
        "name": author.get("name", "Francisco Hernando Gallego"),
        "total_citations": as_int(author.get("citedby")),
        "citations_5y": as_int(author.get("citedby5y")),
        "hindex": as_int(author.get("hindex")),
        "hindex5y": as_int(author.get("hindex5y")),
        "i10index": as_int(author.get("i10index")),
        "i10index5y": as_int(author.get("i10index5y")),
        "citations_current_year": as_int(current_year_citations),
        "cites_per_year": cites_per_year,
        "publications": sorted(
            publications,
            key=lambda paper: (as_int(paper["year"]), paper["citations"], paper["title"]),
            reverse=True,
        ),
    }


def validate_snapshot(snapshot: dict, previous: dict | None) -> None:
    """Refuse incomplete Scholar responses instead of publishing false zeroes."""
    if not snapshot["publications"]:
        raise RuntimeError("Google Scholar returned no publications; keeping the last valid data")
    if snapshot["total_citations"] <= 0:
        raise RuntimeError("Google Scholar returned an invalid citation total; keeping the last valid data")
    if not previous or not previous.get("publications"):
        return
    if snapshot["total_citations"] < as_int(previous.get("total_citations")):
        raise RuntimeError("Google Scholar returned a lower citation total; keeping the last valid data")
    previous_count = len(previous["publications"])
    if len(snapshot["publications"]) < previous_count * 0.8:
        raise RuntimeError("Google Scholar returned an incomplete publication list; keeping the last valid data")


def render_publications_html(publications: list[dict]) -> str:
    rows = []
    for paper in publications:
        title = html.escape(paper["title"])
        year = html.escape(paper["year"] or "—")
        venue = html.escape(paper["venue"])
        url = html.escape(paper["url"], quote=True)
        citations = paper["citations"]
        metadata = f"{venue} · " if venue else ""
        rows.append(
            '        <li class="publication" itemscope itemtype="https://schema.org/ScholarlyArticle">'
            f'<span class="pub-year" itemprop="datePublished">{year}</span><div>'
            f'<a class="pub-title" itemprop="url" href="{url}"><span itemprop="headline">{title}</span></a>'
            f'<p class="pub-doi">{metadata}<a href="{url}">Google Scholar</a>'
            f'<span class="citation-live" data-scholar-citations>{citations}</span></p></div></li>'
        )
    return "\n".join(rows)


def render_publications_llms(publications: list[dict]) -> str:
    lines = []
    for paper in publications:
        authors = f"{paper['authors']}. " if paper["authors"] else ""
        year = f" ({paper['year']})" if paper["year"] else ""
        venue = f" {paper['venue']}" if paper["venue"] else ""
        lines.append(
            f"- {authors}\"{paper['title']}\"{year}.{venue} "
            f"Google Scholar citations: {paper['citations']}. URL: {paper['url']}"
        )
    return "\n".join(lines)


def replace_publication_block(text: str, rendered: str) -> str:
    replacement = (
        "\n        <!-- scholar-publications:start -->\n"
        f"{rendered}\n"
        "        <!-- scholar-publications:end -->"
    )
    updated, count = PUBLICATIONS_BLOCK.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Scholar publication markers are missing or duplicated")
    return updated


def update_public_pages(snapshot: dict) -> None:
    updated_at = snapshot["updated_at"][:10]
    publications_html = render_publications_html(snapshot["publications"])
    for relative in ("index.html", "es/index.html"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for key in METRIC_KEYS:
            text = re.sub(
                rf'(<strong data-scholar="{key}">).*?(</strong>)',
                rf"\g<1>{snapshot[key]}\g<2>",
                text,
            )
        text = re.sub(
            r'(<time data-scholar-updated datetime=")[^"]*(">).*?(</time>)',
            rf"\g<1>{updated_at}\g<2>{updated_at}\g<3>",
            text,
        )
        path.write_text(replace_publication_block(text, publications_html), encoding="utf-8")

    llms_path = ROOT / "llms.txt"
    llms = llms_path.read_text(encoding="utf-8")
    replacements = {
        "Google Scholar citations": snapshot["total_citations"],
        "Google Scholar citations (5 years)": snapshot["citations_5y"],
        "Google Scholar h-index": snapshot["hindex"],
        "Google Scholar h-index (5 years)": snapshot["hindex5y"],
        "Google Scholar i10-index": snapshot["i10index"],
        "Google Scholar i10-index (5 years)": snapshot["i10index5y"],
        "Google Scholar citations (current year)": snapshot["citations_current_year"],
        "Scholar metrics updated": updated_at,
    }
    for label, value in replacements.items():
        llms = re.sub(
            rf"^{re.escape(label)}:.*$",
            f"{label}: {value}",
            llms,
            flags=re.MULTILINE,
        )
    llms = replace_publication_block(llms, render_publications_llms(snapshot["publications"]))
    llms_path.write_text(llms, encoding="utf-8")


def main() -> None:
    previous = load_previous()
    snapshot = fetch_snapshot()
    validate_snapshot(snapshot, previous)
    DATA_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with HISTORY_FILE.open("a", encoding="utf-8") as history:
        history.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    update_public_pages(snapshot)
    print(
        f"Scholar updated: {len(snapshot['publications'])} publications, "
        f"{snapshot['total_citations']} citations, h-index {snapshot['hindex']}"
    )


if __name__ == "__main__":
    main()
