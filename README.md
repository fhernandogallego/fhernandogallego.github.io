# Francisco Hernando Gallego — academic website

Bilingual academic website published with GitHub Pages. English is the default language and Spanish is available under `/es/`.

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
2. Updates `data/scholar.json` and appends a snapshot to `data/scholar-history.jsonl`.
3. Writes the latest citation and h-index figures into both language versions and `llms.txt`.
4. Commits and pushes changed public metrics to `main`.
5. Optionally sends a Telegram notification when citations increase.

When the Scholar workflow finishes, `.github/workflows/deploy-pages.yml` publishes the resulting repository state. It also deploys after ordinary pushes to `main`.

Google Scholar may occasionally block automated requests from shared GitHub Actions IP addresses. A failed run does not overwrite the last valid data. If blocks become frequent, use a stable proxy or a supported scholarly-data API rather than increasing the request frequency.

## Telegram secrets

Never store the bot token or chat ID in the repository. Create these GitHub Actions secrets under **Settings → Secrets and variables → Actions → New repository secret**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The token previously pasted into a script should be revoked with BotFather and replaced before configuring the secret.

## Run the updater locally

Install the pinned dependencies used by the workflow and execute:

```bash
python -m pip install scholarly==1.7.11 requests==2.32.5
python scripts/update_scholar.py
```

For optional Telegram notifications, provide `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as environment variables. Do not add them to a committed file.

## Discovery files

- `sitemap.xml` and `robots.txt` support web crawling.
- `llms.txt` provides a compact, machine-readable academic identity and selected bibliography.
- Visible publication summaries, DOI links and Schema.org markup improve semantic discovery.
- The University of Valladolid portal, ORCID and Google Scholar remain the authoritative external profiles.
