"""Refresh every publication and metric from a public Google Scholar profile."""

from __future__ import annotations

import html
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from journal_data import attach_journal_indicators


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "scholar.json"
HISTORY_FILE = ROOT / "data" / "scholar-history.jsonl"
SUMMARIES_FILE = ROOT / "data" / "publication-summaries.json"
METADATA_FILE = ROOT / "data" / "publication-metadata.json"
OVERRIDES_FILE = ROOT / "data" / "publication-overrides.json"
AUTHOR_ID = os.environ.get("SCHOLAR_AUTHOR_ID", "89e5aoQAAAAJ")
ACADEMIC_NAME = "F. Hernando-Galego"
PUBLICATIONS_BLOCK = re.compile(
    r"(?P<start>\s*<!-- scholar-publications:start -->).*?"
    r"(?P<end>\s*<!-- scholar-publications:end -->)",
    re.DOTALL,
)
CITATIONS_CHART_BLOCK = re.compile(
    r"(?P<start>\s*<!-- scholar-chart:start -->).*?"
    r"(?P<end>\s*<!-- scholar-chart:end -->)",
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


def normalize_academic_name(value: str) -> str:
    """Use the author's canonical academic signature in generated discovery text."""
    normalized = value
    for variant in (
        "Francisco Hernando-Gallego",
        "Francisco Hernando Gallego",
        "F Hernando-Gallego",
        "F. Hernando-Gallego",
        "F Hernando-Galego",
    ):
        normalized = normalized.replace(variant, ACADEMIC_NAME)
    return normalized


def publication_authors(paper: dict) -> list[str]:
    authors = normalize_academic_name(paper.get("authors") or ACADEMIC_NAME)
    return [author.strip() for author in re.split(r"\s+and\s+", authors) if author.strip()]


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


def scholar_publication_url(paper: dict) -> str:
    publication_id = paper.get("author_pub_id", "")
    if publication_id:
        return (
            "https://scholar.google.com/citations?view_op=view_citation"
            f"&hl=en&user={quote(AUTHOR_ID)}&citation_for_view={quote(publication_id)}"
        )
    return f"https://scholar.google.com/citations?user={quote(AUTHOR_ID)}"


def slugify_publication(paper: dict) -> str:
    normalized = unicodedata.normalize("NFKD", paper["title"]).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:72].rstrip("-")
    identity = paper.get("author_pub_id") or paper["title"]
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"{paper.get('year') or 'undated'}-{words}-{suffix}"


def ensure_slugs(publications: list[dict]) -> None:
    for paper in publications:
        paper["slug"] = paper.get("slug") or slugify_publication(paper)


def load_summaries() -> dict:
    return json.loads(SUMMARIES_FILE.read_text(encoding="utf-8"))


def load_publication_metadata() -> dict:
    if not METADATA_FILE.exists():
        return {}
    return json.loads(METADATA_FILE.read_text(encoding="utf-8"))


def load_publication_overrides() -> dict:
    return json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))


def publication_summary(title: str, language: str, summaries: dict) -> str:
    normalized = title.casefold()
    for prefix, translations in summaries.items():
        if normalized.startswith(prefix.casefold()):
            return str(translations.get(language) or "")
    return ""


def apply_curated_metadata(publications: list[dict], summaries: dict) -> None:
    metadata = load_publication_metadata()
    overrides = load_publication_overrides()
    for paper in publications:
        slug = paper.get("slug", "")
        record = {**metadata.get(slug, {}), **overrides.get(slug, {})}
        if record.get("status") in {"matched", "curated"}:
            for key in (
                "doi", "journal", "publisher", "published", "volume", "issue", "pages", "type",
                "issns", "openalex_id", "open_access_url", "repository_url",
            ):
                if record.get(key):
                    paper[key] = record[key]
            if record.get("authors"):
                paper["authors"] = " and ".join(record["authors"])
        normalized = paper["title"].casefold()
        for prefix, note in summaries.items():
            if normalized.startswith(prefix.casefold()):
                if note.get("doi"):
                    paper["doi"] = note["doi"]
                break


def fetch_snapshot(previous: dict | None = None) -> dict:
    """Download the complete profile and normalize it for the static website."""
    from scholarly import scholarly

    author = scholarly.fill(
        scholarly.search_author_id(AUTHOR_ID),
        sections=["basics", "indices", "counts", "publications"],
    )
    previous_publications = (previous or {}).get("publications", [])
    previous_by_id = {
        paper.get("author_pub_id"): paper
        for paper in previous_publications
        if paper.get("author_pub_id")
    }
    publications = []
    for item in author.get("publications", []):
        bib = item.get("bib", {}) or {}
        publication_id = str(item.get("author_pub_id") or "")
        prior = previous_by_id.get(publication_id, {})
        title = str(bib.get("title") or "")
        venue = str(bib.get("citation") or bib.get("venue") or "")
        # Existing records already contain the slow detail-page fields. Scholar
        # is queried in depth only for a genuinely new profile publication.
        if not prior and (not bib.get("author") or not bib.get("pub_year") or not venue or title.endswith(("…", "..."))):
            try:
                item = scholarly.fill(item)
                bib = item.get("bib", {}) or bib
            except Exception:  # Scholar can throttle individual detail pages.
                pass
        current_title = str(bib.get("title") or "")
        if current_title.endswith(("…", "...")) and prior.get("title"):
            current_title = prior["title"]
        direct_url = item.get("pub_url") or item.get("eprint_url")
        publications.append(
            {
                "title": current_title or prior.get("title") or title or "Untitled",
                "authors": author_text(bib.get("author")) or prior.get("authors", ""),
                "year": str(bib.get("pub_year") or prior.get("year") or ""),
                "venue": str(bib.get("citation") or bib.get("venue") or prior.get("venue") or venue),
                "citations": as_int(item.get("num_citations")),
                "author_pub_id": publication_id,
                "url": str(direct_url or prior.get("url") or publication_url(item)),
            }
        )

    now = datetime.now(timezone.utc)
    cites_per_year = author.get("cites_per_year", {}) or {}
    current_year_citations = cites_per_year.get(now.year, cites_per_year.get(str(now.year), 0))
    publications.sort(
        key=lambda paper: (as_int(paper["year"]), paper["citations"], paper["title"]),
        reverse=True,
    )
    ensure_slugs(publications)
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
        "publications": publications,
    }


def import_snapshot(path: Path, previous: dict | None) -> dict:
    """Convert the lightweight snapshot produced by the existing server bot."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    previous = previous or {}
    previous_publications = previous.get("publications", [])
    previous_by_id = {
        paper.get("author_pub_id"): paper
        for paper in previous_publications
        if paper.get("author_pub_id")
    }
    publications = []
    for item in raw.get("publications", []):
        publication_id = str(item.get("author_pub_id") or "")
        prior = previous_by_id.get(publication_id, {})
        paper = {
            "title": str(item.get("title") or prior.get("title") or "Untitled"),
            "authors": author_text(item.get("authors") or prior.get("authors")),
            "year": str(item.get("year") or prior.get("year") or ""),
            "venue": str(item.get("venue") or prior.get("venue") or ""),
            "citations": as_int(item.get("citations")),
            "author_pub_id": publication_id,
            "url": str(item.get("url") or prior.get("url") or publication_url(item)),
        }
        if prior.get("slug"):
            paper["slug"] = prior["slug"]
        publications.append(paper)

    publications.sort(
        key=lambda paper: (as_int(paper["year"]), paper["citations"], paper["title"]),
        reverse=True,
    )
    ensure_slugs(publications)
    snapshot = {
        "updated_at": str(raw.get("updated_at") or raw.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "source": "Google Scholar",
        "profile": str(raw.get("profile") or previous.get("profile") or f"https://scholar.google.com/citations?user={AUTHOR_ID}"),
        "name": str(raw.get("name") or previous.get("name") or "Francisco Hernando-Gallego"),
        "cites_per_year": raw.get("cites_per_year") or previous.get("cites_per_year", {}),
        "publications": publications,
    }
    for key in METRIC_KEYS:
        snapshot[key] = as_int(raw[key] if key in raw else previous.get(key))
    return snapshot


def save_snapshot(snapshot: dict) -> None:
    DATA_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with HISTORY_FILE.open("a", encoding="utf-8") as history:
        history.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    update_public_pages(snapshot)


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


def render_publications_html(publications: list[dict], language: str) -> str:
    rows = []
    ordered = sorted(
        publications,
        key=lambda paper: (paper["citations"], as_int(paper["year"]), paper["title"].casefold()),
        reverse=True,
    )
    for paper in ordered:
        title = html.escape(paper["title"])
        year = html.escape(paper["year"] or "—")
        data_year = as_int(paper["year"])
        venue = html.escape(paper.get("journal") or paper["venue"])
        url = html.escape(scholar_publication_url(paper), quote=True)
        detail_url = html.escape(f"publications/{paper['slug']}/", quote=True)
        publication_id = html.escape(paper.get("author_pub_id", ""), quote=True)
        citations = paper["citations"]
        published_html = (
            f'<time itemprop="datePublished" datetime="{year}">{year}</time>'
            if year != "—" else ""
        )
        metadata = " · ".join(value for value in (published_html, venue) if value) or "—"
        indicators = paper.get("journal_indicators") or {}
        citescore = indicators.get("citescore") or {}
        indicator_html = ""
        if citescore.get("best_quartile"):
            quartile = html.escape(citescore["best_quartile"])
            quartile_title = (
                "Mejor cuartil CiteScore 2025 entre las categorías de Scopus"
                if language == "es" else
                "Best CiteScore 2025 quartile across Scopus categories"
            )
            indicator_html += f'<span class="quartile-badge" title="{quartile_title}">{quartile}</span>'
        if indicators:
            listed = indicators.get("behaviour_listed", False)
            marker = "⚠" if listed else "○"
            marker_class = "report-listed" if listed else "report-clear"
            if language == "es":
                marker_title = (
                    "Incluida en el informe bibliométrico aportado sobre comportamiento no estándar; no es un veto oficial de ANECA"
                    if listed else
                    "No identificada en el informe bibliométrico aportado; no equivale a una aprobación de ANECA"
                )
            else:
                marker_title = (
                    "Included in the supplied non-standard-behaviour report; this is not an official ANECA ban"
                    if listed else
                    "Not identified in the supplied bibliometric report; this is not an ANECA endorsement"
                )
            indicator_html += (
                f'<span class="journal-report-marker {marker_class}" role="img" '
                f'aria-label="{html.escape(marker_title, quote=True)}" '
                f'title="{html.escape(marker_title, quote=True)}">{marker}</span>'
            )
        indicator_html = (
            f'<span class="journal-flags">{indicator_html}</span>'
            if indicator_html else
            f'<span class="journal-empty" aria-label="{"No aplicable" if language == "es" else "Not applicable"}">—</span>'
        )
        citation_label = "citas en Google Scholar" if language == "es" else "Google Scholar citations"
        rows.append(
            f'          <tr class="publication" data-year="{data_year}" data-citations="{citations}" '
            f'data-scholar-id="{publication_id}" itemscope itemtype="https://schema.org/ScholarlyArticle">'
            f'<td class="pub-main"><a class="pub-title" itemprop="url" href="{detail_url}">'
            f'<span itemprop="headline">{title}</span></a>'
            f'<p class="pub-doi">{metadata}</p></td>'
            f'<td class="pub-quality">{indicator_html}</td>'
            f'<td class="pub-citations"><a href="{url}" aria-label="{citation_label}">'
            f'<span class="citation-live" data-scholar-citations>{citations}</span></a></td></tr>'
        )
    return "\n".join(rows)


def render_citations_chart(cites_per_year: dict, language: str) -> str:
    values = []
    for raw_year, raw_citations in cites_per_year.items():
        try:
            values.append((int(raw_year), as_int(raw_citations)))
        except (TypeError, ValueError):
            continue
    values = sorted(values)[-8:]
    maximum = max((citations for _, citations in values), default=1) or 1
    label = "citas" if language == "es" else "citations"
    bars = []
    for year, citations in values:
        height = max(3, round(citations / maximum * 100, 1)) if citations else 0
        accessible = f"{year}: {citations} {label}"
        bars.append(
            f'          <div class="citation-bar" role="img" aria-label="{accessible}">'
            f'<span class="bar-value">{citations}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="height:{height}%"></span></span>'
            f'<span class="bar-year">{year}</span></div>'
        )
    return "\n".join(bars)


def render_publications_llms(publications: list[dict]) -> str:
    lines = []
    for paper in publications:
        authors = f"{' and '.join(publication_authors(paper))}. "
        year = f" ({paper['year']})" if paper["year"] else ""
        venue = f" {paper['venue']}" if paper["venue"] else ""
        doi = f" DOI: https://doi.org/{paper['doi']}." if paper.get("doi") else ""
        indicators = paper.get("journal_indicators") or {}
        citescore = indicators.get("citescore") or {}
        journal_facts = ""
        if citescore:
            ranks = "; ".join(
                f"{category['name']}: {category['rank']}/{category['rank_out_of']} ({category['quartile']})"
                for category in citescore.get("categories", [])
            )
            journal_facts += (
                f" Scopus CiteScore 2025: {citescore.get('citescore')}; "
                f"best quartile: {citescore.get('best_quartile')}; category ranks: {ranks}."
            )
        if indicators:
            status = "listed" if indicators.get("behaviour_listed") else "not identified"
            journal_facts += f" Journal status in the supplied 2017-2019 non-standard-behaviour report: {status}."
        lines.append(
            f"- {authors}\"{paper['title']}\"{year}.{venue} "
            f"Google Scholar citations: {paper['citations']}.{doi}{journal_facts} URL: {paper['url']}"
        )
    return "\n".join(lines)


def bibtex_value(value: object) -> str:
    escapes = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
    }
    return "".join(escapes.get(character, character) for character in str(value or ""))


def write_bibtex(publications: list[dict]) -> None:
    entries = []
    for paper in publications:
        authors = " and ".join(publication_authors(paper))
        year = paper.get("year") or "nd"
        title_word = next((word.title() for word in re.findall(r"[A-Za-z]+", paper["title"]) if len(word) > 3), "Work")
        key = f"HernandoGalego{year}{title_word}{paper['slug'][-4:]}"
        entry_type = {
            "journal-article": "article",
            "proceedings-article": "inproceedings",
            "book-chapter": "incollection",
        }.get(paper.get("type"), "article" if paper.get("journal") else "misc")
        fields = {
            "author": authors,
            "title": paper["title"],
            "year": paper.get("year"),
            "journal": paper.get("journal"),
            "volume": paper.get("volume"),
            "number": paper.get("issue"),
            "pages": paper.get("pages"),
            "doi": paper.get("doi"),
            "url": f"https://www.fransdata.com/publications/{paper['slug']}/",
        }
        rendered_fields = ",\n".join(
            f"  {name} = {{{bibtex_value(value)}}}" for name, value in fields.items() if value
        )
        entries.append(f"@{entry_type}{{{key},\n{rendered_fields}\n}}")
    (ROOT / "publications.bib").write_text("\n\n".join(entries) + "\n", encoding="utf-8")


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


def replace_citations_chart(text: str, rendered: str) -> str:
    replacement = (
        "\n        <!-- scholar-chart:start -->\n"
        f"{rendered}\n"
        "        <!-- scholar-chart:end -->"
    )
    updated, count = CITATIONS_CHART_BLOCK.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Scholar chart markers are missing or duplicated")
    return updated


def render_publication_page(paper: dict, language: str, summaries: dict) -> str:
    spanish = language == "es"
    title = paper["title"]
    slug = paper["slug"]
    summary = publication_summary(title, language, summaries)
    year = paper["year"] or "Undated"
    published = paper.get("published") or paper["year"] or ""
    author_names = publication_authors(paper)
    authors = " · ".join(author_names)
    venue = paper["venue"] or ("Registro de Google Scholar" if spanish else "Google Scholar record")
    canonical = f"https://www.fransdata.com/{'es/' if spanish else ''}publications/{slug}/"
    alternate = f"https://www.fransdata.com/{'' if spanish else 'es/'}publications/{slug}/"
    scholar_url = scholar_publication_url(paper)
    doi = paper.get("doi", "")
    doi_url = f"https://doi.org/{doi}" if doi else ""
    description = summary or (
        f"Ficha bibliográfica y citas de la publicación «{title}» de {ACADEMIC_NAME}."
        if spanish else
        f"Bibliographic and citation record for “{title}” by {ACADEMIC_NAME}."
    )
    indicators = paper.get("journal_indicators") or {}
    citescore = indicators.get("citescore") or {}
    schema = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": title,
        "author": [
            {
                "@type": "Person",
                "name": author,
                **({"url": "https://www.fransdata.com/"} if author == ACADEMIC_NAME else {}),
            }
            for author in author_names
        ],
        "datePublished": published or None,
        "description": summary or None,
        "url": canonical,
        "sameAs": [
            url for url in (
                doi_url,
                scholar_url,
                paper.get("url", ""),
                paper.get("openalex_id", ""),
                paper.get("repository_url", ""),
            ) if url
        ],
        "isPartOf": {"@type": "Periodical", "name": paper.get("journal") or venue},
    }
    if citescore:
        schema["additionalProperty"] = [
            {
                "@type": "PropertyValue",
                "name": "Scopus CiteScore 2025",
                "value": citescore.get("citescore"),
            },
            {
                "@type": "PropertyValue",
                "name": "Best Scopus CiteScore quartile 2025",
                "value": citescore.get("best_quartile"),
            },
            *[
                {
                    "@type": "PropertyValue",
                    "name": f"Scopus category rank: {category['name']}",
                    "value": f"{category['rank']}/{category['rank_out_of']} ({category['quartile']})",
                }
                for category in citescore.get("categories", [])
            ],
        ]
    schema = {key: value for key, value in schema.items() if value is not None}
    schema_json = json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")
    labels = {
        "back": "Volver a publicaciones" if spanish else "Back to publications",
        "record": "Ficha de publicación" if spanish else "Publication record",
        "authors": "Autores" if spanish else "Authors",
        "published": "Publicación" if spanish else "Published in",
        "citations": "Citas en Google Scholar" if spanish else "Google Scholar citations",
        "summary": "Resumen de investigación" if spanish else "Research summary",
        "summary_note": (
            "Descripción original preparada para esta web; consulte la publicación para el abstract oficial."
            if spanish else
            "Original description prepared for this website; consult the publication for its authoritative abstract."
        ),
        "source": "Ver registro en Google Scholar" if spanish else "View Google Scholar record",
        "open": "Versión de acceso abierto" if spanish else "Open-access version",
        "repository": "Registro en repositorio" if spanish else "Repository record",
        "language": "English" if spanish else "Español",
        "journal_indicators": "Indicadores de la revista" if spanish else "Journal indicators",
        "citescore": "CiteScore 2025 (Scopus)",
        "best_quartile": "Mejor cuartil" if spanish else "Best quartile",
        "top": "Top 10 % en alguna categoría" if spanish else "Top 10% in any category",
        "positions": "Posiciones por categoría" if spanish else "Positions by category",
        "scopus_source": "Fuente en Scopus" if spanish else "Scopus source",
        "jcr": "JCR (Clarivate)",
        "jcr_unverified": (
            "No verificado: el fichero aportado es CiteScore de Scopus, no JCR."
            if spanish else
            "Not verified: the supplied ranking file is Scopus CiteScore, not JCR."
        ),
        "listed_report": (
            "Incluida en el informe aportado sobre comportamiento bibliométrico no estándar (2017–2019)."
            if spanish else
            "Included in the supplied report on non-standard bibliometric behaviour (2017–2019)."
        ),
        "not_listed_report": (
            "No identificada en el informe aportado sobre comportamiento bibliométrico no estándar (2017–2019)."
            if spanish else
            "Not identified in the supplied report on non-standard bibliometric behaviour (2017–2019)."
        ),
        "report_note": (
            "El informe es un análisis independiente publicado en 2021; no es una lista oficial de veto o aprobación de ANECA."
            if spanish else
            "The report is an independent analysis published in 2021; it is not an official ANECA ban or endorsement list."
        ),
        "not_found": (
            "Revista no encontrada en el fichero CiteScore 2025 aportado."
            if spanish else
            "Journal not found in the supplied CiteScore 2025 file."
        ),
        "percentile": "percentil" if spanish else "percentile",
        "yes": "Sí" if spanish else "Yes",
        "no": "No" if spanish else "No",
    }
    summary_html = ""
    if summary:
        summary_html = (
            f'      <section class="paper-summary"><h2>{labels["summary"]}</h2>'
            f'<p>{html.escape(summary)}</p><small>{labels["summary_note"]}</small></section>'
        )
    citation_authors = "\n".join(
        f'<meta name="citation_author" content="{html.escape(author, quote=True)}">'
        for author in author_names
    )
    citation_meta = (
        f'<meta name="citation_title" content="{html.escape(title, quote=True)}">\n'
        f'{citation_authors}\n'
        f'<meta name="citation_publication_date" content="{html.escape(str(published or year), quote=True)}">\n'
        f'<meta name="citation_public_url" content="{html.escape(canonical, quote=True)}">'
    )
    if doi:
        citation_meta += f'\n<meta name="citation_doi" content="{html.escape(doi, quote=True)}">'
    if paper.get("journal"):
        citation_meta += f'\n<meta name="citation_journal_title" content="{html.escape(paper["journal"], quote=True)}">'
    if paper.get("volume"):
        citation_meta += f'\n<meta name="citation_volume" content="{html.escape(paper["volume"], quote=True)}">'
    if paper.get("issue"):
        citation_meta += f'\n<meta name="citation_issue" content="{html.escape(paper["issue"], quote=True)}">'
    if paper.get("pages"):
        page_parts = re.split(r"[-–—]", paper["pages"], maxsplit=1)
        citation_meta += f'\n<meta name="citation_firstpage" content="{html.escape(page_parts[0].strip(), quote=True)}">'
        if len(page_parts) == 2:
            citation_meta += f'\n<meta name="citation_lastpage" content="{html.escape(page_parts[1].strip(), quote=True)}">'
    doi_link = (
        f'<a href="{html.escape(doi_url, quote=True)}">DOI {html.escape(doi)} ↗</a> · '
        if doi else ""
    )
    open_link = (
        f'<a href="{html.escape(paper["open_access_url"], quote=True)}">{labels["open"]} ↗</a> · '
        if paper.get("open_access_url") else ""
    )
    repository_link = (
        f'<a href="{html.escape(paper["repository_url"], quote=True)}">{labels["repository"]} ↗</a> · '
        if paper.get("repository_url") else ""
    )
    journal_indicators_html = ""
    if indicators:
        behaviour = indicators.get("behaviour") or {}
        report_status = labels["listed_report"] if behaviour else labels["not_listed_report"]
        report_marker = "⚠" if behaviour else "○"
        report_class = "report-listed" if behaviour else "report-clear"
        metrics_html = f'<p class="journal-missing">{labels["not_found"]}</p>'
        if citescore:
            category_rows = []
            for category in citescore.get("categories", []):
                top_label = " · Top 10%" if category.get("top_10_percent") else ""
                category_rows.append(
                    '<li>'
                    f'<strong>{html.escape(str(category["name"]))}</strong>'
                    f'<span>{category["rank"]}/{category["rank_out_of"]} · '
                    f'{html.escape(str(category["quartile"]))} · {labels["percentile"]} '
                    f'{category["percentile"]}{top_label}</span>'
                    '</li>'
                )
            categories = "".join(category_rows)
            metrics_html = (
                '<div class="journal-summary">'
                f'<p><span>{labels["citescore"]}</span><strong>{citescore.get("citescore", "—")}</strong></p>'
                f'<p><span>{labels["best_quartile"]}</span><strong class="quartile-badge">'
                f'{html.escape(citescore.get("best_quartile") or "—")}</strong></p>'
                f'<p><span>{labels["top"]}</span><strong>'
                f'{labels["yes"] if citescore.get("top_10_percent") else labels["no"]}</strong></p>'
                '</div>'
                f'<h3>{labels["positions"]}</h3><ul class="journal-categories">{categories}</ul>'
                f'<p class="journal-source"><a href="{html.escape(citescore.get("url") or "", quote=True)}">'
                f'{labels["scopus_source"]} ↗</a></p>'
            )
        journal_indicators_html = (
            f'      <section class="journal-indicators"><h2>{labels["journal_indicators"]}</h2>'
            f'{metrics_html}'
            f'<p class="jcr-status"><strong>{labels["jcr"]}:</strong> {labels["jcr_unverified"]}</p>'
            f'<p class="report-status {report_class}"><span aria-hidden="true">{report_marker}</span> '
            f'{report_status}</p><small>{labels["report_note"]}</small></section>'
        )
    return f'''<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — Francisco Hernando-Gallego</title>
  <meta name="description" content="{html.escape(description, quote=True)}">
  <meta name="robots" content="index,follow,max-snippet:-1">
  <link rel="canonical" href="{canonical}">
  <link rel="alternate" hreflang="en" href="https://www.fransdata.com/publications/{slug}/">
  <link rel="alternate" hreflang="es" href="https://www.fransdata.com/es/publications/{slug}/">
  <link rel="alternate" hreflang="x-default" href="https://www.fransdata.com/publications/{slug}/">
  <link rel="icon" type="image/png" sizes="96x96" href="/assets/favicon-short-hair.png">
  <link rel="stylesheet" href="/css/styles.css">
  {citation_meta}
  <script type="application/ld+json">{schema_json}</script>
</head>
<body>
  <main class="paper-page">
    <nav class="paper-nav"><a href="{'/es/' if spanish else '/'}">← {labels['back']}</a><a href="{alternate}" hreflang="{'en' if spanish else 'es'}">{labels['language']}</a></nav>
    <article class="paper-detail">
      <p class="paper-kicker">{labels['record']} · {html.escape(str(year))}</p>
      <h1>{html.escape(title)}</h1>
      <dl>
        <div><dt>{labels['authors']}</dt><dd>{html.escape(authors)}</dd></div>
        <div><dt>{labels['published']}</dt><dd>{html.escape(venue)}</dd></div>
        <div><dt>{labels['citations']}</dt><dd>{paper['citations']}</dd></div>
      </dl>
{journal_indicators_html}
{summary_html}
      <p class="paper-source">{doi_link}{open_link}{repository_link}<a href="{html.escape(scholar_url, quote=True)}">{labels['source']} ↗</a></p>
    </article>
  </main>
</body>
</html>
'''


def write_publication_pages(snapshot: dict) -> None:
    ensure_slugs(snapshot["publications"])
    summaries = load_summaries()
    for language, base in (("en", ROOT / "publications"), ("es", ROOT / "es" / "publications")):
        for paper in snapshot["publications"]:
            destination = base / paper["slug"] / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_publication_page(paper, language, summaries), encoding="utf-8")


def update_sitemap(publications: list[dict]) -> None:
    urls = [
        ("https://www.fransdata.com/", "1.0"),
        ("https://www.fransdata.com/es/", "0.9"),
        ("https://www.fransdata.com/supervision/", "0.7"),
        ("https://www.fransdata.com/es/supervision/", "0.7"),
        ("https://www.fransdata.com/projects/", "0.7"),
        ("https://www.fransdata.com/es/projects/", "0.7"),
    ]
    for paper in publications:
        urls.extend(
            [
                (f"https://www.fransdata.com/publications/{paper['slug']}/", "0.8"),
                (f"https://www.fransdata.com/es/publications/{paper['slug']}/", "0.8"),
            ]
        )
    entries = "".join(
        f"<url><loc>{html.escape(url)}</loc><changefreq>monthly</changefreq><priority>{priority}</priority></url>"
        for url, priority in urls
    )
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n',
        encoding="utf-8",
    )


def update_public_pages(snapshot: dict) -> None:
    updated_at = snapshot["updated_at"][:10]
    ensure_slugs(snapshot["publications"])
    summaries = load_summaries()
    apply_curated_metadata(snapshot["publications"], summaries)
    attach_journal_indicators(snapshot["publications"])
    for relative, language in (("index.html", "en"), ("es/index.html", "es")):
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
        text = re.sub(
            r'(<strong data-publication-count>).*?(</strong>)',
            rf"\g<1>{len(snapshot['publications'])}\g<2>",
            text,
        )
        publications_html = render_publications_html(snapshot["publications"], language)
        text = replace_publication_block(text, publications_html)
        text = replace_citations_chart(text, render_citations_chart(snapshot.get("cites_per_year", {}), language))
        path.write_text(text, encoding="utf-8")

    for relative in ("supervision/index.html", "projects/index.html", "es/supervision/index.html", "es/projects/index.html"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r'(<strong data-publication-count>).*?(</strong>)',
            rf"\g<1>{len(snapshot['publications'])}\g<2>",
            text,
        )
        path.write_text(text, encoding="utf-8")

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
    write_publication_pages(snapshot)
    write_bibtex(snapshot["publications"])
    update_sitemap(snapshot["publications"])


def main() -> None:
    if "--render-only" in sys.argv:
        snapshot = load_previous()
        if not snapshot:
            raise RuntimeError("No Scholar snapshot is available to render")
        apply_curated_metadata(snapshot["publications"], load_summaries())
        update_public_pages(snapshot)
        print(f"Rendered {len(snapshot['publications'])} publications from stored data")
        return
    previous = load_previous()
    if "--snapshot-file" in sys.argv:
        option_index = sys.argv.index("--snapshot-file")
        try:
            snapshot_path = Path(sys.argv[option_index + 1]).expanduser()
        except IndexError as error:
            raise RuntimeError("--snapshot-file requires a path") from error
        snapshot = import_snapshot(snapshot_path, previous)
    else:
        snapshot = fetch_snapshot(previous)
    apply_curated_metadata(snapshot["publications"], load_summaries())
    validate_snapshot(snapshot, previous)
    save_snapshot(snapshot)
    print(
        f"Scholar updated: {len(snapshot['publications'])} publications, "
        f"{snapshot['total_citations']} citations, h-index {snapshot['hindex']}"
    )


if __name__ == "__main__":
    main()
