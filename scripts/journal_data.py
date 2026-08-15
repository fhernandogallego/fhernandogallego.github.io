"""Load and match the repository's journal-level bibliometric datasets."""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CITESCORE_FILE = ROOT / "data" / "citescore-2025.json.gz"
BEHAVIOUR_FILE = ROOT / "data" / "journal-behaviour-2017-2019.json"


def normalize_journal_name(value: object) -> str:
    """Normalize journal titles conservatively for exact catalogue matching."""
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    ascii_value = ascii_value.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def normalize_issn(value: object) -> str:
    return re.sub(r"[^0-9x]", "", str(value or "").casefold())


# Crossref and Scholar sometimes use the shorter title while Scopus retains a
# geographical qualifier. These aliases are explicit so a fuzzy match can
# never attach another journal's metrics.
CITESCORE_ALIASES = {
    normalize_journal_name("Applied Sciences"): normalize_journal_name("Applied Sciences (Switzerland)"),
    normalize_journal_name("Earth"): normalize_journal_name("Earth (Switzerland)"),
}

# The 2021 report uses a few legacy JCR spellings (and one source typo).
BEHAVIOUR_ALIASES = {
    normalize_journal_name("Applied Sciences"): normalize_journal_name("Applied Sciences-Basel"),
    normalize_journal_name("Symmetry"): normalize_journal_name("Simetry-Basel"),
    normalize_journal_name("Viruses"): normalize_journal_name("Viruses-Basel"),
}


@lru_cache(maxsize=1)
def load_citescore_catalogue() -> dict:
    if not CITESCORE_FILE.exists():
        return {"metadata": {}, "journals": []}
    with gzip.open(CITESCORE_FILE, "rt", encoding="utf-8") as source:
        return json.load(source)


@lru_cache(maxsize=1)
def load_behaviour_catalogue() -> dict:
    if not BEHAVIOUR_FILE.exists():
        return {"metadata": {}, "journals": []}
    return json.loads(BEHAVIOUR_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def citescore_indexes() -> tuple[dict[str, dict], dict[str, dict]]:
    by_title: dict[str, dict] = {}
    by_issn: dict[str, dict] = {}
    for journal in load_citescore_catalogue().get("journals", []):
        by_title[normalize_journal_name(journal.get("title"))] = journal
        for issn in journal.get("issns", []):
            normalized = normalize_issn(issn)
            if normalized:
                by_issn[normalized] = journal
    return by_title, by_issn


@lru_cache(maxsize=1)
def behaviour_index() -> dict[str, dict]:
    return {
        normalize_journal_name(journal.get("title")): journal
        for journal in load_behaviour_catalogue().get("journals", [])
    }


def match_citescore(journal_name: str, issns: list[str] | None = None) -> dict | None:
    by_title, by_issn = citescore_indexes()
    for issn in issns or []:
        match = by_issn.get(normalize_issn(issn))
        if match:
            return match
    key = normalize_journal_name(journal_name)
    return by_title.get(key) or by_title.get(CITESCORE_ALIASES.get(key, ""))


def match_behaviour(journal_name: str) -> dict | None:
    index = behaviour_index()
    key = normalize_journal_name(journal_name)
    return index.get(key) or index.get(BEHAVIOUR_ALIASES.get(key, ""))


def attach_journal_indicators(publications: list[dict]) -> None:
    """Attach source-labelled indicators to journal articles for rendering."""
    for paper in publications:
        paper.pop("journal_indicators", None)
        journal = str(paper.get("journal") or "").strip()
        if not journal or paper.get("type") != "journal-article":
            continue
        metrics = match_citescore(journal, paper.get("issns") or [])
        behaviour = match_behaviour(journal)
        paper["journal_indicators"] = {
            "journal": journal,
            "citescore": metrics,
            "behaviour": behaviour,
            "behaviour_listed": bool(behaviour),
        }
