"""Refresh public Google Scholar metrics and optionally notify Telegram.

Secrets are read only from the environment. Never commit them to the repository.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from scholarly import scholarly


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "scholar.json"
HISTORY_FILE = ROOT / "data" / "scholar-history.jsonl"
AUTHOR_ID = os.environ.get("SCHOLAR_AUTHOR_ID", "89e5aoQAAAAJ")


def load_previous() -> dict | None:
    if not DATA_FILE.exists():
        return None
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def fetch_snapshot() -> dict:
    author = scholarly.fill(
        scholarly.search_author_id(AUTHOR_ID),
        sections=["basics", "indices", "counts", "publications"],
    )
    publications = []
    for item in author.get("publications", []):
        bib = item.get("bib", {})
        publications.append(
            {
                "title": bib.get("title", "Untitled"),
                "year": bib.get("pub_year"),
                "citations": int(item.get("num_citations", 0) or 0),
                "author_pub_id": item.get("author_pub_id", ""),
            }
        )
    now = datetime.now(timezone.utc)
    cites_per_year = author.get("cites_per_year", {}) or {}
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "Google Scholar",
        "profile": f"https://scholar.google.com/citations?user={AUTHOR_ID}",
        "name": author.get("name", "Francisco Hernando Gallego"),
        "total_citations": int(author.get("citedby", 0) or 0),
        "hindex": int(author.get("hindex", 0) or 0),
        "i10index": int(author.get("i10index", 0) or 0),
        "citations_current_year": int(cites_per_year.get(now.year, 0) or 0),
        "cites_per_year": cites_per_year,
        "publications": sorted(
            publications,
            key=lambda paper: (paper.get("citations", 0), paper.get("title", "")),
            reverse=True,
        ),
    }


def publication_key(publication: dict) -> str:
    return publication.get("author_pub_id") or publication.get("title", "")


def citation_changes(previous: dict | None, current: dict) -> list[dict]:
    if not previous or current["total_citations"] <= int(previous.get("total_citations", 0) or 0):
        return []
    old = {publication_key(p): p for p in previous.get("publications", []) if publication_key(p)}
    changes = []
    for paper in current["publications"]:
        prior = old.get(publication_key(paper))
        if not prior:
            continue
        delta = paper["citations"] - int(prior.get("citations", 0) or 0)
        if delta > 0:
            changes.append({**paper, "previous": prior["citations"], "delta": delta})
    return changes


def update_public_pages(snapshot: dict) -> None:
    values = {
        "total_citations": str(snapshot["total_citations"]),
        "hindex": str(snapshot["hindex"]),
    }
    updated = snapshot["updated_at"][:10]
    for relative in ("index.html", "es/index.html"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for key, value in values.items():
            text = re.sub(
                rf'(<strong data-scholar="{key}">).*?(</strong>)',
                rf"\g<1>{value}\g<2>",
                text,
            )
        text = re.sub(
            r'(<time data-scholar-updated datetime=")[^"]*(">).*?(</time>)',
            rf"\g<1>{updated}\g<2>{updated}\g<3>",
            text,
        )
        path.write_text(text, encoding="utf-8")

    llms_path = ROOT / "llms.txt"
    llms = llms_path.read_text(encoding="utf-8")
    replacements = {
        "Google Scholar citations": snapshot["total_citations"],
        "Google Scholar h-index": snapshot["hindex"],
        "Google Scholar i10-index": snapshot["i10index"],
        "Scholar metrics updated": updated,
    }
    for label, value in replacements.items():
        pattern = rf"^{re.escape(label)}:.*$"
        line = f"{label}: {value}"
        llms = re.sub(pattern, line, llms, flags=re.MULTILINE) if re.search(pattern, llms, re.MULTILINE) else llms + f"\n{line}"
    llms_path.write_text(llms, encoding="utf-8")


def notify_telegram(previous: dict | None, current: dict, changes: list[dict]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not previous:
        return
    total_delta = current["total_citations"] - int(previous.get("total_citations", 0) or 0)
    if total_delta <= 0:
        return
    lines = [
        "📚 <b>Nuevas citas en Google Scholar</b>",
        "",
        f"📈 Citas: <b>{previous.get('total_citations', 0)} → {current['total_citations']}</b> (+{total_delta})",
        f"🏅 Índice h: <b>{current['hindex']}</b>",
    ]
    for paper in changes:
        lines.extend(
            [
                "",
                f"• <b>{html.escape(paper['title'])}</b>",
                f"  {paper['previous']} → {paper['citations']} (+{paper['delta']})",
            ]
        )
    lines.extend(["", current["profile"]])
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"},
        timeout=20,
    )
    response.raise_for_status()


def main() -> None:
    previous = load_previous()
    current = fetch_snapshot()
    changes = citation_changes(previous, current)
    DATA_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with HISTORY_FILE.open("a", encoding="utf-8") as history:
        history.write(json.dumps(current, ensure_ascii=False) + "\n")
    update_public_pages(current)
    notify_telegram(previous, current, changes)
    print(f"Scholar updated: {current['total_citations']} citations, h-index {current['hindex']}")


if __name__ == "__main__":
    main()
