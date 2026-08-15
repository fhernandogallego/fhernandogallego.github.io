# Francisco Hernando Gallego — academic website

Bilingual academic website published with GitHub Pages. English is the default language and Spanish is available under `/es/`.

The canonical academic signature is **Hernando-Galego, F.** (`F. Hernando-Galego` in display order). Earlier name variants are retained only as identity aliases for discovery and disambiguation.

## Publish with GitHub Pages

1. Push this repository to `fhernandogallego/fhernandogallego.github.io` on the `main` branch.
2. Open the repository on GitHub and go to **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **GitHub Actions**.
4. Open **Actions → Deploy academic website to Pages** and run it once, or push a commit to `main`.
5. The site will be available at `https://www.fransdata.com/` after the first deployment finishes. The repository keeps its existing `CNAME` configuration for this custom domain.

The repository must be public for free GitHub Pages on a standard GitHub Free account. The workflow needs permission to write its daily metrics commit: under **Settings → Actions → General → Workflow permissions**, select **Read and write permissions**.

## Daily Google Scholar update

The workflow [`.github/workflows/update-scholar.yml`](.github/workflows/update-scholar.yml) runs every day at 06:17 UTC and can also be launched manually from **Actions → Update Google Scholar metrics → Run workflow**.

It performs the following tasks:

1. Reads the public Scholar profile `89e5aoQAAAAJ`.
2. Downloads the complete publication list and all available citation, h-index and i10-index metrics, including five-year values. Any new work appearing on the profile is therefore added automatically.
3. Enriches new or unresolved records with conservatively matched Crossref, OpenAlex and arXiv metadata, including DOI, complete authorship, open-access locations and journal fields.
4. Rebuilds the publication lists and the individual bilingual publication pages, updates `data/scholar.json`, appends a historical snapshot and refreshes `llms.txt` and `sitemap.xml`.
5. Commits and pushes changed public metrics to `main`.

When the Scholar workflow finishes, `.github/workflows/deploy-pages.yml` publishes the resulting repository state. It also deploys after ordinary pushes to `main`.

Google Scholar may occasionally block automated requests from shared GitHub Actions IP addresses. A failed run does not overwrite the last valid data. If blocks become frequent, use a stable proxy or a supported scholarly-data API rather than increasing the request frequency.

## Run the updater locally

Install the pinned dependencies used by the workflow and execute:

```bash
python -m pip install scholarly==1.7.11
python scripts/update_scholar.py
python scripts/enrich_publications.py
python scripts/update_scholar.py --render-only
```

## Discovery files

- `sitemap.xml` and `robots.txt` support web crawling.
- `llms.txt` provides a compact, machine-readable academic identity and selected bibliography.
- Every Scholar publication has a stable bilingual URL with Google Scholar citation meta tags and Schema.org `ScholarlyArticle` markup.
- `publications.bib` provides a complete bibliography for reference managers and citing authors.
- `data/publication-summaries.json` stores original, curated summaries and verified DOI values separately from third-party publisher abstracts.
- The homepage stays compact while publication pages provide richer machine-readable context.
- The University of Valladolid portal, ORCID and Google Scholar remain the authoritative external profiles.
- Bilingual pages list supervised bachelor's theses and current research, knowledge-transfer and teaching-innovation projects from the CVN dated 14 August 2026.
