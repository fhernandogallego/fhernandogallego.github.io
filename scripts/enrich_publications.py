"""Enrich Scholar publications with conservatively matched Crossref metadata."""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHOLAR_FILE = ROOT / "data" / "scholar.json"
METADATA_FILE = ROOT / "data" / "publication-metadata.json"
CONTACT_EMAIL = "fhernando@uva.es"
USER_AGENT = f"fransdata-academic-site/1.0 (mailto:{CONTACT_EMAIL})"
ACADEMIC_NAME = "F. Hernando-Galego"


def normalized(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def canonical_author(given: str, family: str) -> str:
    name = " ".join(part for part in (given, family) if part).strip()
    key = normalized(name)
    if "hernando gallego" in key or "hernando galego" in key:
        return ACADEMIC_NAME
    return name


def unique_authors(authors: list[str]) -> list[str]:
    result = []
    for author in authors:
        if author and author not in result:
            result.append(author)
    return result


def issued_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None


def issued_date(item: dict) -> str:
    for key in ("published-print", "published-online", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if not parts or not parts[0]:
            continue
        values = [int(value) for value in parts[0][:3]]
        return "-".join(f"{value:02d}" if index else str(value) for index, value in enumerate(values))
    return ""


def query_crossref(title: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "query.title": title,
            "rows": 5,
            "mailto": CONTACT_EMAIL,
            "select": (
                "DOI,title,author,container-title,publisher,published-print,"
                "published-online,issued,created,type,URL,abstract,volume,issue,page,link"
            ),
        }
    )
    request = urllib.request.Request(
        f"https://api.crossref.org/works?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["message"]["items"]
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    return []


def candidate_score(paper: dict, candidate: dict) -> float:
    candidate_title = (candidate.get("title") or [""])[0]
    score = difflib.SequenceMatcher(None, normalized(paper["title"]), normalized(candidate_title)).ratio()
    paper_year = int(paper["year"]) if str(paper.get("year", "")).isdigit() else None
    candidate_year = issued_year(candidate)
    if paper_year and candidate_year and abs(paper_year - candidate_year) > 1:
        score -= 0.12
    venue = normalized(paper.get("venue", ""))
    container = normalized(" ".join(candidate.get("container-title") or []))
    if venue and container and (container in venue or venue in container):
        score += 0.03
    return min(score, 1.0)


def should_skip(paper: dict, duplicated_titles: set[str]) -> str:
    venue = normalized(paper.get("venue", ""))
    title = normalized(paper["title"])
    if title in duplicated_titles and not venue:
        return "ambiguous duplicate without venue"
    if "arxiv" in venue:
        return "arXiv record"
    if "patent" in venue:
        return "patent record"
    return ""


def select_match(paper: dict, candidates: list[dict]) -> tuple[dict | None, float]:
    ranked = sorted(
        ((candidate_score(paper, candidate), candidate) for candidate in candidates),
        key=lambda value: value[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.94:
        return None, ranked[0][0] if ranked else 0.0
    score, candidate = ranked[0]
    venue = normalized(paper.get("venue", ""))
    candidate_type = candidate.get("type", "")
    if "preprints" in venue and candidate_type != "posted-content":
        return None, score
    return candidate, score


def clean_abstract(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def openalex_abstract(index: dict | None) -> str:
    if not index:
        return ""
    words = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(words))


def query_openalex(paper: dict, record: dict) -> dict | None:
    doi = record.get("doi") or ""
    if doi:
        target = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    else:
        params = urllib.parse.urlencode({"search": paper["title"], "per-page": 3, "mailto": CONTACT_EMAIL})
        target = f"https://api.openalex.org/works?{params}"
    request = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if doi:
        return payload
    candidates = payload.get("results", [])
    ranked = sorted(
        [
            (
                difflib.SequenceMatcher(
                    None,
                    normalized(paper["title"]),
                    normalized(candidate.get("title") or ""),
                ).ratio(),
                candidate,
            )
            for candidate in candidates
        ],
        key=lambda value: value[0],
    )
    if not ranked or ranked[-1][0] < 0.96:
        return None
    return ranked[-1][1]


def arxiv_id(paper: dict) -> str:
    match = re.search(r"arxiv:\s*([0-9.]+)", paper.get("venue", ""), re.IGNORECASE)
    return match.group(1) if match else ""


def query_arxiv(identifier: str) -> dict | None:
    request = urllib.request.Request(
        f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(identifier)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", namespace)
    if entry is None:
        return None
    return {
        "authors": [
            canonical_author("", node.findtext("atom:name", default="", namespaces=namespace))
            for node in entry.findall("atom:author", namespace)
        ],
        "published": entry.findtext("atom:published", default="", namespaces=namespace)[:10],
        "abstract": re.sub(r"\s+", " ", entry.findtext("atom:summary", default="", namespaces=namespace)).strip(),
    }


def crossref_record(candidate: dict, score: float) -> dict:
    authors = unique_authors([
        canonical_author(str(author.get("given") or ""), str(author.get("family") or ""))
        for author in candidate.get("author", [])
    ])
    abstract = clean_abstract(str(candidate.get("abstract") or ""))
    return {
        "status": "matched",
        "source": "Crossref",
        "match_score": round(score, 4),
        "doi": html.unescape(str(candidate.get("DOI") or "")),
        "authors": authors,
        "journal": html.unescape(str((candidate.get("container-title") or [""])[0])),
        "publisher": html.unescape(str(candidate.get("publisher") or "")),
        "published": issued_date(candidate),
        "volume": str(candidate.get("volume") or ""),
        "issue": str(candidate.get("issue") or ""),
        "pages": str(candidate.get("page") or ""),
        "type": str(candidate.get("type") or ""),
        "url": str(candidate.get("URL") or ""),
        "abstract_available": bool(abstract),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Recheck already processed records")
    parser.add_argument("--abstract-cache", type=Path, help="Write retrieved abstracts to a local review file")
    args = parser.parse_args()

    snapshot = json.loads(SCHOLAR_FILE.read_text(encoding="utf-8"))
    metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8")) if METADATA_FILE.exists() else {}
    titles = [normalized(paper["title"]) for paper in snapshot["publications"]]
    duplicated_titles = {title for title in titles if titles.count(title) > 1}
    abstract_cache: dict[str, str] = {}
    if args.abstract_cache and args.abstract_cache.exists():
        abstract_cache = json.loads(args.abstract_cache.read_text(encoding="utf-8"))
    matched = skipped = unresolved = failed = 0

    for paper in snapshot["publications"]:
        identifier = arxiv_id(paper)
        if not identifier:
            continue
        slug = paper["slug"]
        record = metadata.get(slug, {})
        if record.get("arxiv_checked") and not args.refresh:
            continue
        try:
            arxiv = query_arxiv(identifier)
            record["arxiv_checked"] = True
            if arxiv:
                record.update(
                    {
                        "status": "matched",
                        "source": "arXiv",
                        "doi": f"10.48550/arXiv.{identifier}",
                        "authors": unique_authors(arxiv["authors"]),
                        "published": arxiv["published"],
                        "type": "posted-content",
                        "url": f"https://arxiv.org/abs/{identifier}",
                        "open_access_url": f"https://arxiv.org/pdf/{identifier}",
                        "abstract_available": bool(arxiv["abstract"]),
                    }
                )
                if arxiv["abstract"]:
                    abstract_cache[slug] = arxiv["abstract"]
            metadata[slug] = record
        except (OSError, ET.ParseError) as error:
            print(f"arXiv unavailable for {paper['title']}: {error}")
        time.sleep(0.35)

    for paper in snapshot["publications"]:
        slug = paper["slug"]
        existing = metadata.get(slug)
        if existing and existing.get("status") in {"matched", "skipped"} and not args.refresh:
            skipped += 1
            continue
        reason = should_skip(paper, duplicated_titles)
        if reason:
            metadata[slug] = {"status": "skipped", "reason": reason}
            skipped += 1
            continue
        try:
            candidates = query_crossref(paper["title"])
            candidate, score = select_match(paper, candidates)
            if not candidate:
                metadata[slug] = {
                    "status": "unresolved",
                    "best_match_score": round(score, 4),
                }
                unresolved += 1
            else:
                metadata[slug] = crossref_record(candidate, score)
                abstract = clean_abstract(str(candidate.get("abstract") or ""))
                if abstract:
                    abstract_cache[slug] = abstract
                matched += 1
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            print(f"Crossref unavailable for {paper['title']}: {error}")
            failed += 1
        time.sleep(0.35)

    for paper in snapshot["publications"]:
        slug = paper["slug"]
        record = metadata.get(slug, {})
        for key in ("journal", "publisher"):
            if record.get(key):
                record[key] = html.unescape(record[key])
        if record.get("authors"):
            record["authors"] = unique_authors(record["authors"])
        if record.get("openalex_checked") and not args.refresh:
            continue
        if record.get("reason") == "patent record":
            record["openalex_checked"] = True
            continue
        try:
            work = query_openalex(paper, record)
            record["openalex_checked"] = True
            if work:
                record["openalex_id"] = work.get("id") or ""
                oa = work.get("open_access") or {}
                location = work.get("best_oa_location") or {}
                if oa.get("is_oa"):
                    record["open_access_url"] = location.get("pdf_url") or location.get("landing_page_url") or ""
                if not record.get("authors"):
                    record["authors"] = unique_authors([
                        canonical_author("", str((authorship.get("author") or {}).get("display_name") or ""))
                        for authorship in work.get("authorships", [])
                    ])
                abstract = openalex_abstract(work.get("abstract_inverted_index"))
                record["abstract_available"] = bool(abstract) or bool(record.get("abstract_available"))
                if abstract and slug not in abstract_cache:
                    abstract_cache[slug] = abstract
            metadata[slug] = record
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            print(f"OpenAlex unavailable for {paper['title']}: {error}")
        time.sleep(0.15)

    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.abstract_cache:
        args.abstract_cache.write_text(
            json.dumps(abstract_cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Crossref enrichment: {matched} matched, {unresolved} unresolved, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
