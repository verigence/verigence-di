#!/usr/bin/env bash
# =============================================================================
# setup.sh — Create verigence-di repo on GitHub and push scaffold
#
# Prerequisites (all installed and authenticated):
#   - git
#   - gh (GitHub CLI)  → brew install gh
#
# Usage:
#   1. Open Terminal
#   2. cd to the folder CONTAINING verigence-di/  (i.e. the IDBP folder)
#   3. bash verigence-di/setup.sh
# =============================================================================

set -euo pipefail

REPO_NAME="verigence-di"
ORG="verigence"
DESCRIPTION="Verigence Document Intelligence — standalone backend + operator UI"

echo ""
echo "==========================================="
echo " Verigence DI — GitHub repository setup"
echo "==========================================="
echo ""

# ── 1. Confirm gh is authenticated ──────────────────────────────────────────
echo "▶  Checking GitHub CLI authentication..."
gh auth status
echo ""

# ── 2. Create the repo under the verigence org ──────────────────────────────
echo "▶  Creating github.com/${ORG}/${REPO_NAME}..."
gh repo create "${ORG}/${REPO_NAME}" \
  --private \
  --description "${DESCRIPTION}" \
  --gitignore "" \
  || echo "   (repo may already exist — continuing)"
echo ""

# ── 3. Initialise local git repo and push ───────────────────────────────────
echo "▶  Initialising local git repo..."
cd "$(dirname "$0")"   # cd into verigence-di/

if [ ! -d ".git" ]; then
  git init
  git checkout -b main
fi

# Rename .gitignore_template to .gitignore if present
if [ -f "gitignore_template" ]; then
  mv gitignore_template .gitignore
fi

git add -A

git diff --cached --quiet && echo "   Nothing to commit." || \
  git commit -m "chore: initial scaffold — Baseline 2.1

- Project structure: backend (FastAPI/Python 3.12) + ops-ui (React PWA)
- Python namespace package: verigence.di
- Domain enums + confidence scoring formula
- StorageAdapter (R2/MinIO S3-compatible)
- DocumentAIAdapter interface + MockAdapter
- SHA-256 hash-chained audit log
- Alembic migration config (DI_POSTGRESQL_SCHEMA_v2.1.sql to follow)
- Docker Compose local dev (PostgreSQL 16 + MinIO)
- GitHub Actions CI/CD: ci.yml, deploy-dev.yml, deploy-prod.yml
- Tests: health endpoints + scoring unit tests

Architecture: DI_ARCHITECTURE_v2.1 / DI_LLD_v2.1 / DI_DATA_MODEL_v2.1"

echo ""
echo "▶  Adding remote and pushing..."
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${ORG}/${REPO_NAME}.git"
git push -u origin main
echo ""

# ── 4. Create the dev branch ─────────────────────────────────────────────────
echo "▶  Creating dev branch..."
git checkout -b dev
git push -u origin dev
git checkout main
echo ""

# ── 5. Set branch protection on main ────────────────────────────────────────
echo "▶  Setting branch protection on main (require PR + CI)..."
gh api \
  --method PUT \
  "repos/${ORG}/${REPO_NAME}/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Backend — lint, typecheck, test", "Frontend — build check"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1
  },
  "restrictions": null
}
JSON
echo ""

# ── 6. Create GitHub Environments ───────────────────────────────────────────
echo "▶  Creating GitHub Environments (di-dev, di-prod)..."
gh api --method PUT "repos/${ORG}/${REPO_NAME}/environments/di-dev" \
  --field wait_timer=0 || true

gh api --method PUT "repos/${ORG}/${REPO_NAME}/environments/di-prod" \
  --field wait_timer=0 || true
echo ""

echo "==========================================="
echo " ✅  Done!"
echo ""
echo " Your repo:  https://github.com/${ORG}/${REPO_NAME}"
echo ""
echo " Next steps:"
echo "  1. Go to Settings → Environments → di-prod"
echo "     Add yourself as a required reviewer (manual deploy gate)"
echo ""
echo "  2. Add these secrets under Settings → Secrets → Actions:"
echo "     DI_DATABASE_URL_DEV   → Neon dev branch connection string"
echo "     DI_DATABASE_URL_PROD  → Neon main branch connection string"
echo "     RAILWAY_TOKEN_DEV     → Railway token for DEV project"
echo "     RAILWAY_TOKEN_PROD    → Railway token for PROD project"
echo ""
echo "  3. Continue with: Step 2 — Alembic initial migration"
echo "==========================================="
