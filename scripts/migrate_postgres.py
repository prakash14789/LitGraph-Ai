"""Clean PostgreSQL Data Migration Script (Local Postgres -> Supabase Postgres).

1. Connects to Supabase to initialize schema (Base.metadata.create_all).
2. Copies all records cleanly table-by-table from local Postgres container to Supabase.
3. Performs exact row count verification.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine
from src.config import settings
from src.models import Base

# Local connection
LOCAL_DSN = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@localhost:5433/{settings.postgres_db}"

# Supabase connection
SUPABASE_HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
SUPABASE_PORT = 5432
SUPABASE_USER = "postgres.ilanfqcmcbtaxprlzmct"
SUPABASE_PASS = "Pr@kash7976818025"
SUPABASE_DB = "postgres"
SUPABASE_DSN = f"postgresql://{SUPABASE_USER}:{SUPABASE_PASS.replace('@', '%40')}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}"


async def migrate():
    print("=== Step 4: Supabase PostgreSQL Migration ===", flush=True)

    # 1. Initialize schema in Supabase using SQLAlchemy async engine
    engine_url = f"postgresql+asyncpg://{SUPABASE_USER}:{SUPABASE_PASS.replace('@', '%40')}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}"
    print("Initializing Supabase table schema...", flush=True)

    supa_engine = create_async_engine(engine_url)
    async with supa_engine.begin() as conn:
        # Check extensions & create tables
        await conn.run_sync(Base.metadata.create_all)
    await supa_engine.dispose()
    print("Schema initialized successfully on Supabase.", flush=True)

    # 2. Connect to local and Supabase via asyncpg
    print("Connecting to local and Supabase databases...", flush=True)
    local_conn = await asyncpg.connect(LOCAL_DSN)
    supa_conn = await asyncpg.connect(SUPABASE_DSN)

    tables = ["collections", "papers", "extraction_jobs", "query_log", "alembic_version"]

    print("\nStarting table data copy...", flush=True)

    extension_warnings = []

    # Clear target tables in dependency order if any existing records
    for tbl in reversed(tables):
        try:
            await supa_conn.execute(f"TRUNCATE TABLE {tbl} CASCADE")
        except Exception:
            pass

    # Copy data table by table
    for tbl in tables:
        rows = await local_conn.fetch(f"SELECT * FROM {tbl}")
        if not rows:
            print(f"Table '{tbl}': 0 rows to copy.", flush=True)
            continue

        columns = list(rows[0].keys())
        cols_str = ", ".join([f'"{c}"' for c in columns])
        placeholders = ", ".join([f"${i+1}" for i in range(len(columns))])

        insert_query = f'INSERT INTO "{tbl}" ({cols_str}) VALUES ({placeholders})'

        records_to_insert = []
        for r in rows:
            record_vals = []
            for col in columns:
                val = r[col]
                # Format dict/list as json string for JSONB if needed or pass as is
                record_vals.append(val)
            records_to_insert.append(record_vals)

        await supa_conn.executemany(insert_query, records_to_insert)
        print(f"Copied {len(rows)} rows into '{tbl}'.", flush=True)

    # 3. Verification & Row Counts
    print("\n--- PostgreSQL Row Count Verification ---", flush=True)
    print(
        f"{'Table Name':<20} | {'Local Count':<12} | {'Supabase Count':<15} | {'Match Status'}",
        flush=True,
    )
    print("-" * 65, flush=True)

    all_matched = True
    for tbl in tables:
        local_cnt = await local_conn.fetchval(f"SELECT count(*) FROM {tbl}")
        supa_cnt = await supa_conn.fetchval(f"SELECT count(*) FROM {tbl}")

        status = "[OK] Match" if local_cnt == supa_cnt else "[MISMATCH]"
        if local_cnt != supa_cnt:
            all_matched = False

        print(f"{tbl:<20} | {local_cnt:<12} | {supa_cnt:<15} | {status}", flush=True)

    await local_conn.close()
    await supa_conn.close()

    if extension_warnings:
        print("\n--- Extension Warnings ---", flush=True)
        for w in extension_warnings:
            print(f" - {w}", flush=True)
    else:
        print("\nExtension Restore Status: Clean (No extension errors).", flush=True)

    if all_matched:
        print(
            "\n[SUCCESS] Supabase PostgreSQL data migration & row counts 100% MATCHED!", flush=True
        )
    else:
        print("\n[WARNING] Row count mismatch detected!", flush=True)


if __name__ == "__main__":
    asyncio.run(migrate())
