"""Write one company's HRMS configuration snapshot to a file (P1-143).

The same document the "Download configuration snapshot" button produces, for generating the
UAT configuration document without a browser. Read-only: nothing is written to the database.

Usage (from backend/):
    python scripts/export_config_snapshot.py --company-id <id> --out uat_config.xlsx
    python scripts/export_config_snapshot.py --company-id <id> --out uat_config.csv
    python scripts/export_config_snapshot.py --company-id <id> --out uat_config.json
The format follows the --out extension.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import certifi
import motor.motor_asyncio

sys.path.insert(0, ".")

from app.config.settings import settings          # noqa: E402
import app.db.mongodb as mongo                    # noqa: E402


async def connect():
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI, tls=True, tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=20000, connectTimeoutMS=20000)
    await client.admin.command("ping")
    mongo.db_connection.client = client
    mongo.db_connection.db = client[settings.DATABASE_NAME]
    return client


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company-id", required=True, help="company_id to export")
    parser.add_argument("--out", required=True, help="output file (.xlsx, .csv or .json)")
    args = parser.parse_args()

    out = Path(args.out)
    fmt = out.suffix.lower().lstrip(".")
    if fmt not in ("xlsx", "csv", "json"):
        parser.error("--out must end in .xlsx, .csv or .json")

    from app.services import hrms_config_snapshot_service as snapshot
    client = await connect()
    try:
        result = await snapshot.export(args.company_id, fmt)
    finally:
        client.close()
    if fmt == "json":
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        sections = result["sections"]
    else:
        out.write_bytes(result[0])
        sections = None
    print(f"Wrote {out}" + (f" ({len(sections)} sections)" if sections else ""))


if __name__ == "__main__":
    asyncio.run(main())
