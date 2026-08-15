import asyncio

import asyncpg


async def check():
    import os
    dsn = os.environ.get("DI_CHECK_PROFILES_DSN", "")
    if not dsn:
        raise SystemExit("Set DI_CHECK_PROFILES_DSN to the Neon connection string")
    conn = await asyncpg.connect(dsn, ssl="require")

    for doc_type in ('pan_card', 'booking_form'):
        print(f'=== extraction profile fields: {doc_type} ===')
        rows = await conn.fetch('''
            SELECT cf.field_key, epf.expected, epf.score_weight, epf.score_included,
                   epf.extraction_instruction
            FROM docintel.extraction_profiles ep
            JOIN docintel.document_types dt
              ON dt.document_type_id = ep.document_type_id
             AND dt.document_type_key = $1
            JOIN docintel.extraction_profile_fields epf
              ON epf.profile_id = ep.profile_id
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = epf.canonical_field_id
            WHERE ep.status = 'PUBLISHED'
              AND epf.enabled = true
            ORDER BY epf.display_sequence, cf.field_key
        ''', doc_type)
        for r in rows:
            print(f'  {r["field_key"]:35s}  expected={r["expected"]}  weight={r["score_weight"]}  score={r["score_included"]}')
            if r["extraction_instruction"]:
                print(f'    instruction: {r["extraction_instruction"][:100]}')
        if not rows:
            print('  (no fields)')
        print()

    # Also check Gemini adapter key and DI_DOCAI_MOCK status from env
    print('=== DI env indicators (from settings) ===')
    import sys
    os.environ.setdefault('DI_SECRET_KEY', 'x' * 32)
    os.environ.setdefault('DI_DATABASE_URL', 'postgresql+asyncpg://x:x@localhost/x')
    sys.path.insert(0, 'src')
    from verigence.di.settings import get_settings
    s = get_settings()
    print(f'  docai_mock          = {s.docai_mock}')
    print(f'  docai_gemini_api_key = {"SET (" + str(len(s.docai_gemini_api_key)) + " chars)" if s.docai_gemini_api_key else "NOT SET"}')
    print(f'  backout_ttl_hours   = {s.backout_ttl_hours}')

    await conn.close()

asyncio.run(check())
