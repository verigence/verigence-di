#!/bin/bash
#
# railway-cost-report.sh
#
# Shows current Railway service status and estimated monthly costs.
# Helps you understand what's running and what it costs.
#
# Prerequisites:
#   - Railway CLI installed
#   - Authenticated with Railway: `railway login`
#
# Usage:
#   ./scripts/railway-cost-report.sh
#

set -e

# Project and service IDs
PROJECT_ID="62c22163-78d0-4a86-a2f7-dbf39e64aa4d"
DI_API_SERVICE_ID="c7286646-fe6f-4cb3-a055-e6e7a71e852a"
DI_WORKER_SERVICE_ID="5c7124fe-8e2a-4abd-8e45-37d248ee56a3"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Railway Cost Report${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo -e "${RED}✗ Railway CLI not found${NC}"
    echo "  Install it: https://docs.railway.app/cli/installation"
    exit 1
fi

echo -e "${YELLOW}Checking authentication...${NC}"
if ! railway whoami &> /dev/null; then
    echo -e "${RED}✗ Not authenticated with Railway${NC}"
    echo "  Run: railway login"
    exit 1
fi
echo -e "${GREEN}✓ Authenticated${NC}"
echo ""

# Function to format status
format_status() {
    local status=$1
    if [[ $status == "RUNNING" ]] || [[ $status == "HEALTHY" ]]; then
        echo -e "${GREEN}$status${NC}"
    elif [[ $status == "STOPPED" ]] || [[ $status == "PAUSED" ]]; then
        echo -e "${YELLOW}$status${NC}"
    else
        echo -e "${RED}$status${NC}"
    fi
}

echo -e "${BLUE}Service Status${NC}"
echo "─────────────────────────────────────────────────────────────"
echo ""

# Check di-api status
echo -n "di-api (FastAPI backend):     "
if railway service status "$DI_API_SERVICE_ID" 2>/dev/null | grep -q "RUNNING"; then
    echo -e "${GREEN}✓ RUNNING${NC}"
    DI_API_RUNNING=1
else
    echo -e "${YELLOW}⏸ PAUSED${NC}"
    DI_API_RUNNING=0
fi

# Check di-worker status
echo -n "di-worker (Job processor):    "
if railway service status "$DI_WORKER_SERVICE_ID" 2>/dev/null | grep -q "RUNNING"; then
    echo -e "${GREEN}✓ RUNNING${NC}"
    DI_WORKER_RUNNING=1
else
    echo -e "${YELLOW}⏸ PAUSED${NC}"
    DI_WORKER_RUNNING=0
fi

echo ""
echo -e "${BLUE}Estimated Monthly Costs (Railway only)${NC}"
echo "─────────────────────────────────────────────────────────────"
echo ""

# Cost estimation (based on Railway's pricing)
# Standard pricing: ~$0.25/hour per running service
DI_API_HOURLY=0.25
DI_WORKER_HOURLY=0.25
HOURS_PER_MONTH=730  # 365 days / 12 months * 24 hours

if [ $DI_API_RUNNING -eq 1 ]; then
    DI_API_MONTHLY=$(echo "$DI_API_HOURLY * $HOURS_PER_MONTH" | bc)
    echo -e "di-api:        ${GREEN}$DI_API_MONTHLY${NC}/month (running)"
else
    echo -e "di-api:        ${YELLOW}$0${NC}/month (paused)"
fi

if [ $DI_WORKER_RUNNING -eq 1 ]; then
    DI_WORKER_MONTHLY=$(echo "$DI_WORKER_HOURLY * $HOURS_PER_MONTH" | bc)
    echo -e "di-worker:     ${GREEN}$DI_WORKER_MONTHLY${NC}/month (running)"
else
    echo -e "di-worker:     ${YELLOW}$0${NC}/month (paused)"
fi

echo ""
echo -e "${BLUE}What This Doesn't Include${NC}"
echo "─────────────────────────────────────────────────────────────"
echo ""
echo "  ⚠️  Neon PostgreSQL (database):  Separate managed service (~$15-50/month)"
echo "  ⚠️  Cloudflare R2 (storage):     Pay-per-use (~$0.015/GB stored)"
echo "  ⚠️  GitHub Actions (CI/CD):      Free tier (generous limits)"
echo ""

if [ $DI_API_RUNNING -eq 0 ] && [ $DI_WORKER_RUNNING -eq 0 ]; then
    echo -e "${MAGENTA}💰 Both services paused — Railway compute costs minimized!${NC}"
    echo ""
    echo "   To resume: ./scripts/railway-services-start.sh"
else
    echo -e "${MAGENTA}⏰ Services running — Railway accruing compute costs${NC}"
    echo ""
    echo "   To save costs: ./scripts/railway-services-stop.sh"
fi

echo ""
echo -e "${BLUE}Useful Links${NC}"
echo "─────────────────────────────────────────────────────────────"
echo ""
echo "  Railway Dashboard:  https://railway.app/project/$PROJECT_ID"
echo "  di-api logs:        railway logs"
echo "  di-worker logs:     railway logs"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
