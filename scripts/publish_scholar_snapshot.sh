#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash scripts/publish_scholar_snapshot.sh /absolute/path/to/scholar_state.json" >&2
  exit 2
fi

snapshot_path="$1"
repository_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repository_root"

git pull --rebase origin main
python3 scripts/update_scholar.py --snapshot-file "$snapshot_path"
python3 scripts/enrich_publications.py
python3 scripts/update_scholar.py --render-only

git add data/scholar.json data/scholar-history.jsonl data/publication-metadata.json \
  index.html es/index.html llms.txt sitemap.xml publications.bib publications es/publications

if git diff --cached --quiet; then
  echo "No public Scholar data changed."
  exit 0
fi

git config user.name "scholar-update-bot"
git config user.email "fhernando@uva.es"
git commit -m "Update Google Scholar metrics"
git pull --rebase origin main
git push origin main
