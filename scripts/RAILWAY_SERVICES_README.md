# Railway Services Management

This directory contains scripts to control Railway services for cost optimization.

## Overview

Verigence DI runs two services on Railway:
- **di-api**: FastAPI backend service
- **di-worker**: Async job processing worker

Since Railway is a **paid service** (based on compute time), these scripts allow you to:
- ⏸️ **Pause services** when not actively developing (saves cost)
- ▶️ **Resume services** when work resumes

## Quick Start

### Stop all services (save costs)
```bash
./scripts/railway-services-stop.sh
```

This pauses both di-api and di-worker. While paused:
- ✅ No compute costs accumulate
- ✅ Data (PostgreSQL, config) is preserved
- ✅ Services can be resumed later with full state intact
- ❌ API is unavailable
- ❌ Background jobs don't process

### Start all services (resume work)
```bash
./scripts/railway-services-start.sh
```

This resumes both services and:
- Waits for di-api to become healthy
- Verifies both services are running
- Confirms you can make API calls

## Prerequisites

1. **Railway CLI installed**
   ```bash
   # macOS / Linux
   npm i -g @railway/cli
   
   # Or via Homebrew (macOS)
   brew install railway
   ```
   
   Verify: `railway --version`

2. **Authenticated with Railway**
   ```bash
   railway login
   ```
   
   Follow the browser prompt to authorize.

3. **Project context** (optional)
   ```bash
   # Set current project
   railway link 62c22163-78d0-4a86-a2f7-dbf39e64aa4d
   ```

## What Each Script Does

### railway-services-stop.sh

**Purpose**: Pause all Railway services to stop compute costs.

**Flow**:
1. Verifies Railway CLI is installed
2. Verifies you're authenticated
3. Attempts to pause di-api service
4. Attempts to pause di-worker service
5. Reports success and provides next steps

**Output Example**:
```
═══════════════════════════════════════════════════════════
Railway Services — STOP
═══════════════════════════════════════════════════════════

Checking authentication...
✓ Authenticated

Stopping services...

Pausing di-api...
✓ di-api paused

Pausing di-worker...
✓ di-worker paused

═══════════════════════════════════════════════════════════
✓ All Railway services stopped
═══════════════════════════════════════════════════════════

Notes:
  • Services are paused and can be resumed with: ./scripts/railway-services-start.sh
  • Neon PostgreSQL is NOT paused (separate managed service)
  • GitHub auto-deployment is still active (next push will restart services)
  • To prevent auto-restart: temporarily disable GitHub integration in Railway dashboard
```

### railway-services-start.sh

**Purpose**: Resume all Railway services after they've been paused.

**Flow**:
1. Verifies Railway CLI is installed
2. Verifies you're authenticated
3. Attempts to resume di-api service
4. Attempts to resume di-worker service
5. Performs health check on di-api
6. Reports final status and dashboard link

**Output Example**:
```
═══════════════════════════════════════════════════════════
Railway Services — START
═══════════════════════════════════════════════════════════

Checking authentication...
✓ Authenticated

Starting services...

Resuming di-api...
✓ di-api resumed

Resuming di-worker...
✓ di-worker resumed

Verifying service health...

Checking di-api health...
✓ di-api is healthy

═══════════════════════════════════════════════════════════
✓ All Railway services started
═══════════════════════════════════════════════════════════

Status:
  • di-api: Starting (will be available in 1-2 minutes)
  • di-worker: Starting (processing jobs)
  • Dashboard: https://railway.app/project/62c22163-78d0-4a86-a2f7-dbf39e64aa4d

If services don't start within 5 minutes:
  1. Check Railway dashboard for errors
  2. Verify environment variables are set
  3. Check logs: railway logs
```

## Important Notes

### GitHub Auto-Deployment

⚠️ **Important**: The repository has GitHub auto-deployment enabled on the `dev` branch.

**What this means**:
- Any push to `dev` **automatically redeploys** services
- If you pause services and then push code, **services will restart**
- If services are paused and you push, costs will resume accumulating

**Solutions**:
1. **Option A**: Don't push to `dev` while services are paused
2. **Option B**: Temporarily disable GitHub integration in Railway dashboard
   - Railway dashboard → Settings → Source → Disconnect
   - Reconnect when ready to resume work

### Neon PostgreSQL

⚠️ **Not managed by these scripts**.

The database is hosted on Neon (managed service), separate from Railway:
- Costs for Neon are **not reduced** when you pause Railway services
- Neon has its own cost model (based on storage + compute-hours)
- To save Neon costs, you must manually suspend the project in Neon dashboard

### Service IDs Reference

From `SECRETS_CHECKLIST.md`:

| Item | ID |
|---|---|
| Project ID | `62c22163-78d0-4a86-a2f7-dbf39e64aa4d` |
| di-api service | `c7286646-fe6f-4cb3-a055-e6e7a71e852a` |
| di-worker service | `5c7124fe-8e2a-4abd-8e45-37d248ee56a3` |
| Environment (prod) | `3e696b3a-1128-4970-b6c0-5a8c25d8fcb0` |

## Troubleshooting

### Script says "Not authenticated"

```bash
# Solution
railway login
```

Follow the browser prompt. Once done, scripts should work.

### Services don't pause

```bash
# Check if they're already paused
railway status

# Manually pause via dashboard
# Railway dashboard → Service → Pause
```

### Services don't resume

**Most likely causes**:
1. Services were deleted (not paused) — need to redeploy
2. Environment variables are missing
3. GitHub integration is disabled

**Solutions**:
```bash
# Option 1: Redeploy from GitHub
git push origin dev

# Option 2: Check logs
railway logs

# Option 3: Manually restart in dashboard
# Railway dashboard → Service → Start
```

### di-api health check times out

This is normal if the service is just starting. The health check waits up to 60 seconds.

- Services typically become healthy within 1-2 minutes
- If still unavailable after 5 minutes, check Railway dashboard for errors
- Verify all environment variables are set (`DI_*` prefixed)

## Manual Alternative (Railway Dashboard)

If scripts don't work, you can manage services manually:

1. Go to https://railway.app/project/62c22163-78d0-4a86-a2f7-dbf39e64aa4d
2. Select di-api service → Settings → Pause
3. Select di-worker service → Settings → Pause
4. To resume: select each service → Settings → Start

## Cost Implications

| Action | Estimated Cost Impact |
|---|---|
| Pause services | ✅ Stops accumulating Railway compute costs |
| Resume services | ⚠️ Compute costs resume |
| Database (Neon) | ⚠️ Independent — not affected by these scripts |
| Storage (R2) | ⚠️ Independent — minimal cost regardless of API/worker state |

**Typical Railway costs**:
- Small workload (like DI development): **$5–20/month** when running
- Paused services: **$0/month** for compute

## When to Pause/Resume

### Good times to pause:
- ✅ End of development day
- ✅ Weekend / extended break
- ✅ Before vacation
- ✅ During code review phase (no deployments)

### When NOT to pause:
- ❌ If you're actively testing changes
- ❌ Before running tests in CI
- ❌ If background jobs are processing
- ❌ If team members are using the API

## See Also

- Railway Dashboard: https://railway.app/
- Railway Docs: https://docs.railway.app/
- CLI Docs: https://docs.railway.app/cli/commands
- Project: Verigence Document Intelligence
