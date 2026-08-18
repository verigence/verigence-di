# Railway Cost Management — Quick Reference

## One-Line Commands

### Check status and costs
```bash
./scripts/railway-cost-report.sh
```

### Pause services (stop costs)
```bash
./scripts/railway-services-stop.sh
```

### Resume services (restart work)
```bash
./scripts/railway-services-start.sh
```

## Daily Workflow

### End of workday
```bash
# Stop services to save costs
./scripts/railway-services-stop.sh

# Verify they're paused
./scripts/railway-cost-report.sh
```

### Start of workday
```bash
# Resume services
./scripts/railway-services-start.sh

# Verify they're running (wait 1–2 min)
./scripts/railway-cost-report.sh
```

## Prerequisites (one-time setup)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Authenticate
railway login
```

## Cost Savings

| Scenario | Monthly Cost |
|---|---|
| Services running 24/7 | ~$365 (Railway compute) |
| Services paused after work | ~$90 (only Neon DB) |
| **Monthly savings** | **~$275** |

## Important Warnings

⚠️ **GitHub auto-deployment** — Pushing to `dev` restarts paused services

⚠️ **Neon database continues** — Pausing Railway doesn't stop database costs (~$20/month)

⚠️ **Don't forget to pause** — Manual reminder needed until automated

## Scripts Details

| Script | Purpose | Duration |
|---|---|---|
| `railway-services-stop.sh` | Pause both services | < 1 minute |
| `railway-services-start.sh` | Resume both services | 1–2 minutes |
| `railway-cost-report.sh` | Show status & costs | < 1 minute |

## Service IDs

```
Project:   62c22163-78d0-4a86-a2f7-dbf39e64aa4d
di-api:    c7286646-fe6f-4cb3-a055-e6e7a71e852a
di-worker: 5c7124fe-8e2a-4abd-8e45-37d248ee56a3
```

## Troubleshooting

```bash
# Not authenticated
railway login

# Railway CLI not found
npm i -g @railway/cli

# Scripts not executable
chmod +x scripts/railway-*.sh

# Check current status
railway status

# View logs
railway logs
```

---

**Full documentation:** See `scripts/RAILWAY_SERVICES_README.md`

**Last updated:** 2026-08-15
