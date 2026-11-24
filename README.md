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

## Teaching materials

The public teaching catalogue is available at `/docencia/` (Spanish) and `/teaching/` (English). The CESTE EWNS course lives at `/ewns/`: four sessions with five interactive exercises each (20 total) and four lecture-slide PDFs (signal, jamming, deception and protection), all inside encrypted HTML wrappers. Exercise numbers correspond to the questions in each session's slide deck. The existing course username and password unlock both exercises and slides; credentials and plaintext PDFs are never committed. The encrypted pages keep `noindex,nofollow`.

To refresh the course from the local `05_EWNS` directory:

```bash
python3 -m pip install cryptography
python3 scripts/prepare_ewns.py /absolute/path/to/05_EWNS --user ceste
```

Enter the existing password when prompted. The script verifies and decrypts only the five wrappers in `04_web_interactiva/publicar/`, adds the four current PDFs from `01_teoria/` inside encrypted wrappers, and writes only encrypted pages plus `style.css` to `ewns/`. It does not modify the source directory. To change credentials, regenerate `publicar/` with the source project's `encrypt.py` first, then rerun this command with the new credentials. Never copy the full course source directory into this public repository. GitHub Pages serves the encrypted files publicly; encryption prevents reading the content without the key, but offline password guessing remains possible and recipients can save decrypted documents.

## Daily Google Scholar update

The workflow [`.github/workflows/update-scholar.yml`](.github/workflows/update-scholar.yml) runs every day at 06:17 UTC and can also be launched manually from **Actions → Update Google Scholar metrics → Run workflow**.

It performs the following tasks:

1. Reads the public Scholar profile `89e5aoQAAAAJ`.
2. Downloads the complete publication list and all available citation, h-index and i10-index metrics, including five-year values. Any new work appearing on the profile is therefore added automatically.
3. Enriches new or unresolved records with conservatively matched Crossref, OpenAlex and arXiv metadata, including DOI, complete authorship, open-access locations and journal fields.
4. Matches journal articles against the repository's CiteScore 2025 catalogue and 2017–2019 bibliometric-behaviour report. New Scholar articles therefore receive journal indicators automatically after their journal metadata is resolved.
5. Rebuilds the publication lists and the individual bilingual publication pages, updates `data/scholar.json`, appends a historical snapshot and refreshes `llms.txt` and `sitemap.xml`.
6. Commits and pushes changed public metrics to `main`.

When the Scholar workflow finishes, `.github/workflows/deploy-pages.yml` publishes the resulting repository state. It also deploys after ordinary pushes to `main`.

Pages deployment uses the upload step's exact artifact ID through GitHub's deployment API, avoiding the artifact SDK's name lookup. The deployment script verifies that the artifact belongs to the current run, retains OIDC authentication, waits for a successful deployment and cancels on timeout. Run its checks with `node --test .github/scripts/deploy-pages.test.cjs`.

Google Scholar may occasionally block automated requests from shared GitHub Actions IP addresses. The scheduled workflow uses `--allow-stale`: HTTP 403 or 429, or a response missing the profile's metric table or publication rows (even with HTTP 200), produces a workflow warning and keeps the last valid snapshot, its update date and its history unchanged. Publication enrichment and rendering can still continue from the stored data. Without a valid stored snapshot, or for other errors (including invalid fetched metrics), the run still fails. Manual refreshes remain strict unless `--allow-stale` is supplied. If blocks persist, the existing server bot can publish its snapshot using the import command below.

A successful workflow run does not guarantee fresh Scholar data: check the warning and the snapshot's `updated_at` timestamp. The website labels this date as the last successful update. For persistent GitHub runner blocks, refresh from a machine that can access Scholar or import a current snapshot from the existing server bot; rendering or redeploying stored data cannot refresh the citation counts.

## Run the updater locally

Install the pinned dependencies used by the workflow and execute:

```bash
python -m pip install beautifulsoup4 requests
python scripts/update_scholar.py
python scripts/enrich_publications.py
python scripts/update_scholar.py --render-only
```

The existing server bot can publish the lightweight JSON snapshot it already writes without querying Scholar a second time:

```bash
python scripts/update_scholar.py --snapshot-file /absolute/path/to/scholar_state.json
python scripts/enrich_publications.py
python scripts/update_scholar.py --render-only
```

The importer preserves verified authors, venues and URLs from the previous website snapshot, while accepting new citation totals and newly discovered profile publications from the bot.

## Journal indicators

- `data/citescore-2025.json.gz` is a compact repository copy of the supplied **Scopus CiteScore 2025** workbook: 32,089 journals with CiteScore, quartiles, category ranks, percentiles and Top 10% flags. CiteScore is not Clarivate JCR, so the site explicitly marks JCR status as unverified instead of inferring it.
- `data/journal-behaviour-2017-2019.json` contains the 1,107 journal names transcribed in the supplied 2021 independent report. The report concerns non-standard self-citation and/or citable-item behaviour in 2017–2019; it is not described as an official ANECA blacklist.
- The homepage displays only the best CiteScore quartile and a compact report marker. Each publication page lists every Scopus category and rank, the Top 10% result, source wording and the report caveat.
- `scripts/import_journal_data.py` reproducibly regenerates both repository datasets from the original workbook and Markdown report. `scripts/journal_data.py` performs conservative exact title/ISSN matching at render time, including for future Scholar publications.

## Discovery files

- `sitemap.xml` and `robots.txt` support web crawling.
- `llms.txt` provides a compact, machine-readable academic identity and selected bibliography.
- Every Scholar publication has a stable bilingual URL with Google Scholar citation meta tags and Schema.org `ScholarlyArticle` markup.
- `publications.bib` provides a complete bibliography for reference managers and citing authors.
- `data/publication-summaries.json` stores original, curated summaries and verified DOI values separately from third-party publisher abstracts.
- The homepage stays compact while publication pages provide richer machine-readable context.
- The University of Valladolid portal, ORCID and Google Scholar remain the authoritative external profiles.
- Bilingual pages list supervised bachelor's theses and current research, knowledge-transfer and teaching-innovation projects from the CVN dated 14 August 2026.
