# verigence-di — Document Intelligence

**Verigence** product module — standalone Document Intelligence service.

Baseline: **2.1** | Status: **BASELINED FOR IMPLEMENTATION**

## What this module does

Accepts evidence from Mobile, Web, API and WhatsApp. Validates integrity and fitness. Classifies documents. Extracts configured fields. Scores confidence (0-100). Derives Human Verification Status. Exposes Tenant + Subject centric REST enquiries.

## Repos in the Verigence org

| Repo | Purpose |
|---|---|
| `verigence-di` | This repo — Document Intelligence backend + operator UI |
| `verigence-web` | Consumer-facing Web PWA (Phase 2) |
| `verigence-mobile` | Mobile app — React Native (Phase 3) |

## Stack

- **Backend**: Python 3.12 · FastAPI · SQLAlchemy · Alembic · Pydantic
- **Operator UI**: React 18 · TypeScript · Vite PWA
- **Database**: PostgreSQL 16 (Neon) · `docintel` schema · RLS
- **Storage**: Cloudflare R2 (S3-compatible)
- **Auth**: Clerk (OIDC/JWT)
- **OCR/AI**: Google Document AI (behind `DocumentAIAdapter`)
- **Hosting**: Railway (API + Worker + Scheduler) · Cloudflare Pages (ops-ui)

## Local development

```bash
cp infra/.env.example infra/.env.local
docker compose -f infra/docker-compose.yml up
```

API: http://localhost:8000  
Docs: http://localhost:8000/docs  
MinIO console: http://localhost:9001

## Project structure

```
verigence-di/
├── backend/          Python FastAPI application
│   ├── src/verigence/di/
│   │   ├── domain/       State machines, value objects, scoring
│   │   ├── api/          FastAPI routers + Pydantic schemas
│   │   ├── application/  Use cases
│   │   ├── repositories/ SQLAlchemy async models
│   │   ├── storage/      StorageAdapter → R2/MinIO
│   │   ├── document_ai/  DocumentAIAdapter → Google Doc AI
│   │   ├── quality/      Quality rule runner + rules
│   │   ├── rules/        Normalizers + validators
│   │   ├── audit/        SHA-256 hash-chain
│   │   ├── workers/      Processing worker
│   │   └── scheduler/    EOD retry + reconciliation
│   └── alembic/      DB migrations
├── ops-ui/           Operator React PWA
└── infra/            Docker Compose + env config
```

## Branching

| Branch | Environment | Deploy trigger |
|---|---|---|
| `main` | Production | Manual approval PR from `dev` |
| `dev` | DEV / UAT | Auto on merge |
| `feature/*` | Local only | PR to `dev` |

## Architecture reference

See `docs/` for the full Baseline 2.1 architecture documents.
