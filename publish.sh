#!/usr/bin/env bash
# Publish the ledger to the live site.
#
#   scan -> review -> promote  (you do these first; see INGESTION.md)
#   ./publish.sh               <- regenerate the pages, commit, push -> Netlify rebuilds
#
# Keyless: build.py is stdlib-only. Commits use this clone's git identity
# (set to your GitHub noreply address), so nothing personal leaks into the public repo.
set -euo pipefail
cd "$(dirname "$0")"

python3 build.py

# Only publish if the data or generated pages actually changed.
if git diff --quiet -- data/ index.html composite-index.html; then
  echo "Nothing to publish (no data/page changes)."
  exit 0
fi

git add -A
git commit -m "data: refresh ledger $(date +%Y-%m-%d)"
git push
echo "Pushed to GitHub — Netlify will rebuild the live site shortly."
