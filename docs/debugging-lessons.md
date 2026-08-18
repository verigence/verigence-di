# Verigence DI — Debugging Lessons (Hard-Won)

Things that wasted time. Read this before starting any debugging session.

---

## 1. JWT tokens expire — always mint and use in the same Python process

**What went wrong:** JWT minted in one shell command, passed to another. By the time the second command ran, the 5-minute TTL was consumed. Got 401/422 and wasted multiple rounds.

**Rule:** Never mint a JWT and export it as a shell variable. Always mint inside the same Python process that makes the HTTP call.

**Correct pattern:**
```python
# mint + use in one block — no gap between them
import httpx
from jwt_helper import mint_jwt

def tok():
    # Fresh token on EVERY call — never reused
    return mint_jwt(tenant_id=TENANT, actor_id="actor",
                    roles=["TENANT_ADMIN"], exp_seconds=120)

with httpx.Client(base_url=BASE, timeout=30) as c:
    r = c.post("/v1/...", headers={"Authorization": f"Bearer {tok()}"}, ...)
```

**Wrong pattern (never do this):**
```bash
TOKEN=$(cd backend && uv run python -c "from jwt_helper import mint_jwt; print(mint_jwt(...))")
# ... other commands ...
curl -H "Authorization: Bearer $TOKEN" ...   # TOKEN IS EXPIRED BY NOW
```

---

## 2. Private key base64 — write to a file, read from the file

**What went wrong:** Pasted the base64-encoded private key as an inline shell string. Shell heredoc escaping, line wrapping, and copy-paste all corrupt long base64 strings silently. Got `Invalid private key` errors 3 times.

**Rule:** Write the key to `/tmp/di_test_key.pem` once per session using Python (which handles base64 correctly), then reference that file.

**Correct pattern:**
```bash
# Step 1 — write key to file once (Python handles base64 cleanly)
python3 -c "
import base64, os
b64 = os.environ['TEST_JWT_PRIVATE_KEY']
open('/tmp/di_test_key.pem', 'w').write(base64.b64decode(b64).decode())
"

# Step 2 — read it back for shell use (macOS base64 needs -i flag)
TEST_JWT_PRIVATE_KEY="$(base64 -i /tmp/di_test_key.pem)" \
  uv run --no-sync python3 - <<'PYEOF'
...
PYEOF
```

**macOS note:** `base64 <file>` fails — use `base64 -i <file>`.

---

## 3. Railway 500 — diagnose against Neon directly, not via the live API

**What went wrong:** Tried to diagnose DB errors by hitting the live Railway URL and reading the response. Got opaque `text/plain 500 Internal Server Error` (Railway's proxy, not FastAPI). Wasted rounds on Railway CLI auth, curl verbose output, etc.

**Rule:** When the live API returns 500, reproduce the DB operation directly against Neon from local. This gives the full `IntegrityError` / `CheckViolationError` / traceback immediately.

**Pattern:**
```bash
cd backend && \
DI_DATABASE_URL="postgresql+asyncpg://neondb_owner:npg_...@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb?ssl=require" \
uv run --no-sync python3 - <<'PYEOF'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
import os

ENGINE = create_async_engine(os.environ["DI_DATABASE_URL"], pool_pre_ping=True)
SF = async_sessionmaker(ENGINE, class_=AsyncSession, expire_on_commit=False)

async def run():
    async with SF() as s:
        try:
            await s.execute(text("... your SQL ..."), {...})
            await s.commit()
            print("✅ OK")
        except Exception as e:
            await s.rollback()
            import traceback; traceback.print_exc()

asyncio.run(run())
PYEOF
```

Also: add the global exception handler to `main.py` early — it converts crashes to JSON 500 with the actual error message, making Railway-side diagnosis possible without log access (already done, commit `1b9e443`).

---

## 4. Check DB constraints before writing SQL — don't guess column values

**What went wrong:** Used `disposition = 'DELETE'` in the retention policy INSERT. The DB check constraint only allows `'PURGE_CONTENT'` or `'KEEP_CONTENT'`. Didn't check before writing.

**Rule:** Before writing any INSERT/UPDATE that sets an enum-like column, query the actual check constraint first.

```sql
SELECT pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'docintel'
  AND t.relname = 'your_table'
  AND c.conname LIKE '%your_column%';
```

---

## 5. Check the actual unique constraint before writing ON CONFLICT

**What went wrong:** Used `ON CONFLICT (tenant_id, retention_policy_id)` — that pair has no unique constraint. The actual unique constraint on `retention_policies` is `(tenant_id, policy_key)`. Got `UniqueViolationError` on the second request.

**Rule:** Before writing any `ON CONFLICT` clause, query the actual unique indexes.

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'docintel' AND tablename = 'your_table';
```

---

## 6. Railway deploy takes 2–3 minutes — wait before testing

**What went wrong:** Pushed a fix, immediately ran the smoke test, got the old error. Repeated this several times.

**Rule:** After `git push origin dev`, always `sleep 90` before testing against the live URL. Railway needs ~90 seconds to detect the push, build, and redeploy.

**Pattern:**
```bash
git push origin dev && sleep 90 && echo "ready to test"
```

---

## 7. Read the schema before writing provisioning code

**What went wrong:** `provision_retention_policy()` was written without first checking the actual column constraints and unique indexes on `docintel.retention_policies`. Three separate bugs resulted (wrong disposition value, wrong ON CONFLICT target, wrong initial assumption about what columns exist).

**Rule:** Before writing any raw SQL against a table you haven't touched before:
```bash
# Get column list
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'docintel' AND table_name = 'your_table' ORDER BY ordinal_position;

# Get all constraints
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'docintel.your_table'::regclass;

# Get all indexes
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname = 'docintel' AND tablename = 'your_table';
```
