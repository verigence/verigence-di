#!/bin/bash
#
# railway-services-start.sh
# 
# Starts all Railway services after they have been paused.
# This is the inverse of railway-services-stop.sh
#
# Prerequisites:
#   - Railway CLI installed: https://docs.railway.app/cli/installation
#   - Authenticated with Railway: `railway login`
#   - RAILWAY_TOKEN env var set (optional, if using API token instead of CLI auth)
#   - Services must have been previously paused with railway-services-stop.sh
#
# Usage:
#   ./scripts/railway-services-start.sh
#
# What it does:
#   1. Resumes di-api service
#   2. Resumes di-worker service
#   3. Waits for services to become healthy
#   4. Reports final status
#
# Note: If services were deleted instead of paused, they need to be
#       redeployed from GitHub. Pushing to the 'dev' branch will
#       trigger auto-deployment and recreate the services.
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
echo -e "${BLUE}Railway Services — START${NC}"
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

# Function to resume a service
resume_service() {
    local service_name=$1
    local service_id=$2
    
    echo -e "${YELLOW}Resuming ${service_name}...${NC}"
    
    # Use Railway API via CLI to resume the service
    if railway service resume "$service_id" 2>/dev/null; then
        echo -e "${GREEN}✓ ${service_name} resumed${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ Could not resume ${service_name}${NC}"
        echo "  The service may need to be redeployed from GitHub."
        echo "  To redeploy: git push origin dev"
        return 1
    fi
}

# Function to check service health
check_health() {
    local service_name=$1
    local url=$2
    local max_attempts=30
    local attempt=1
    
    echo -e "${YELLOW}Checking ${service_name} health...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ ${service_name} is healthy${NC}"
            return 0
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo ""
    echo -e "${YELLOW}⚠ ${service_name} health check timed out${NC}"
    echo "  Service may still be starting. Check Railway dashboard for status."
    return 1
}

echo -e "${BLUE}Starting services...${NC}"
echo ""

# Resume services
resume_service "di-api" "$DI_API_SERVICE_ID"
echo ""
resume_service "di-worker" "$DI_WORKER_SERVICE_ID"
echo ""

# Check health of di-api (di-worker doesn't have a health endpoint)
echo -e "${BLUE}Verifying service health...${NC}"
echo ""
check_health "di-api" "https://verigence-di-production.up.railway.app" || true

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ All Railway services started${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Status:${NC}"
echo "  • di-api: Starting (will be available in 1-2 minutes)"
echo "  • di-worker: Starting (processing jobs)"
echo "  • Dashboard: https://railway.app/project/$PROJECT_ID"
echo ""
echo -e "${YELLOW}If services don't start within 5 minutes:${NC}"
echo "  1. Check Railway dashboard for errors"
echo "  2. Verify environment variables are set"
echo "  3. Check logs: railway logs"
echo ""
