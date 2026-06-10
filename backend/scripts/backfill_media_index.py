"""One-time backfill: extract searchable text for Media Library files that were
uploaded before content indexing existed.

For every media_library doc of an indexable type (audio/video/pdf/document) that
has no `content_text` yet, download it from S3, extract its text/transcript, and
save it — so the assistant can answer questions about already-uploaded files too.

Safe to re-run: it skips anything already indexed (content_status == completed).
Run from backend/:  python -m scripts.backfill_media_index
"""
import asyncio

from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
from app.services.media_index_service import index_media_library_item, INDEXABLE_TYPES


async def main() -> None:
    await connect_to_mongo()
    try:
        col = get_collection("media_library")
        query = {
            "media_type": {"$in": list(INDEXABLE_TYPES)},
            "s3_key": {"$exists": True, "$ne": None},
            "content_status": {"$ne": "completed"},
        }
        docs = await col.find(query).to_list(10000)
        print(f"Found {len(docs)} media file(s) needing indexing.")

        done = 0
        for d in docs:
            mid = str(d["_id"])
            name = d.get("file_name") or d.get("name") or "media"
            print(f"  [{done + 1}/{len(docs)}] {name} ({d.get('media_type')}) ...", flush=True)
            # Reuse the exact production indexer (download → extract → save).
            await index_media_library_item(mid, d["s3_key"], name, d.get("media_type"))
            done += 1

        print(f"Done. Indexed {done} file(s).")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
