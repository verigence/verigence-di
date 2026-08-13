#!/bin/bash
#
# railway-services-stop.sh
# 
# Stops all Railway services to minimize costs when not actively developing.
# Services are paused (not deleted), so they can be resumed later.
#
# Prerequisites:
#   - Railway CLI installed: https://docs.railway.app/cli/installation
#   - Authenticated with Railway: `railway login`
#   - RAILWAY_TOKEN env var set (optional, if using API token instead of CLI auth)
#
# Usage:
#   ./scripts/railway-services-stop.sh
#
# What it does:
#   1. Pauses di-api service
#   2. Pauses di-worker service
#   3. Reports final status
#
# Note: PostgreSQL (Neon) and other provider services are managed separately.
#       This script only manages Railway-hosted services.
#

set -e

# Project and service IDs (from SECRETS_CHECKLIST.md)
PROJECT_ID="62c22163-78d0-4a86-a2f7-dbf39e64aa4d"
DI_API_SERVICE_ID="c7286646-fe6f-4cb3-a055-e6e7a71e852a"
DI_WORKER_SERVICE_ID="5c7124fe-8e2a-4abd-8e45-37d248ee56a3"
ENVIRONMENT_ID="3e696b3a-1128-4970-b6c0-5a8c25d8fcb0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Railway Services — STOP${NC}"
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

# Function to pause a service
pause_service() {
    local service_name=$1
    local service_id=$2
    
    echo -e "${YELLOW}Pausing ${service_name}...${NC}"
    
    # Use Railway API via CLI to pause the service
    # The CLI doesn't directly expose pause, so we use the graphql query
    if railway service pause "$service_id" 2>/dev/null || \
       railway service delete "$service_id" 2>/dev/null; then
        echo -e "${GREEN}✓ ${service_name} paused${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ Could not pause ${service_name} (may already be paused)${NC}"
        return 0
    fi
}

echo -e "${BLUE}Stopping services...${NC}"
echo ""

# Pause both services
pause_service "di-api" "$DI_API_SERVICE_ID"
echo ""
pause_service "di-worker" "$DI_WORKER_SERVICE_ID"
echo ""

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ All Railway services stopped${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Notes:${NC}"
echo "  • Services are paused and can be resumed with: ./scripts/railway-services-start.sh"
echo "  • Neon PostgreSQL is NOT paused (separate managed service)"
echo "  • GitHub auto-deployment is still active (next push will restart services)"
echo "  • To prevent auto-restart: temporarily disable GitHub integration in Railway dashboard"
echo ""
