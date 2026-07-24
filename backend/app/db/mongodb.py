import motor.motor_asyncio
import certifi
import ssl
from fastapi import HTTPException, status
from app.config.settings import settings

class Database:
    client: motor.motor_asyncio.AsyncIOMotorClient = None
    db = None

db_connection = Database()

async def connect_to_mongo():
    try:
        # Configuration for stability on Windows
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        db_connection.client = motor.motor_asyncio.AsyncIOMotorClient(
            settings.MONGODB_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=20000,
            connectTimeoutMS=20000
        )
        
        # Test connection with a ping
        await db_connection.client.admin.command('ping')
        
        # Select the database
        db_connection.db = db_connection.client[settings.DATABASE_NAME]
        
        # Create TTL index for password resets (10 minutes expiry)
        await db_connection.db["password_resets"].create_index("expires_at", expireAfterSeconds=0)

        # Provision the TPMS form collections (one "table" per form) with indexes.
        await _ensure_form_collections(db_connection.db)

        # Provision the TPMS core collections (activities, escalations, scores, …).
        await _ensure_tpms_collections(db_connection.db)

        print(f"[OK] Successfully connected to MongoDB Atlas (Database: {settings.DATABASE_NAME})")
        
    except Exception as e:
        print(f"[FAILED] connect to MongoDB: {e}")
        db_connection.db = None

async def _ensure_form_collections(db):
    """Idempotently create one collection ("table") per TPMS form with a unique
    (company_id, period, respondent) index + reporting indexes. The respondent is
    `md_id` for the Yes/No checklist and `hod_id` for the rating matrices. Failures
    here must never block startup, so they're logged and swallowed."""
    try:
        from app.models.forms import FORM_COLLECTIONS, FORM_DEFINITIONS, KIND_YESNO_CHECKLIST
        existing = set(await db.list_collection_names())
        for form_type, coll_name in FORM_COLLECTIONS.items():
            kind = (FORM_DEFINITIONS.get(form_type) or {}).get("kind")
            respondent = "md_id" if kind == KIND_YESNO_CHECKLIST else "hod_id"
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            coll = db[coll_name]
            await coll.create_index(
                [("company_id", 1), ("period", 1), (respondent, 1)],
                unique=True, name="uniq_company_period_respondent",
            )
            await coll.create_index([("company_id", 1)], name="by_company")
            await coll.create_index([("period", 1)], name="by_period")
    except Exception as e:
        print(f"[WARN] Could not provision TPMS form collections: {e}")


async def _ensure_tpms_collections(db):
    """Idempotently create the TPMS core collections and their indexes from the single
    spec in app.models.tpms.TPMS_INDEXES, then seed the two master-data tables
    (activity catalogue + reminder rules) if they are empty.

    Seeding is insert-only and skipped once rows exist, so an operator's edits and the
    xlsx migration are never overwritten. As with the form collections, failures here
    must never block startup."""
    try:
        from app.models.tpms import (
            TPMS_INDEXES, ACTIVITY_SEED, REMINDER_RULE_SEED,
            COLL_ACTIVITIES, COLL_REMINDER_RULES,
        )
        existing = set(await db.list_collection_names())
        for coll_name, keys, options in TPMS_INDEXES:
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                    existing.add(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            try:
                await db[coll_name].create_index(keys, **options)
            except Exception as ie:
                # An index conflicting with pre-existing data shouldn't kill startup.
                print(f"[WARN] TPMS index {options.get('name')} on {coll_name}: {ie}")

        # Seed master data only when the collection is completely empty.
        for coll_name, seed in ((COLL_ACTIVITIES, ACTIVITY_SEED),
                                (COLL_REMINDER_RULES, REMINDER_RULE_SEED)):
            if await db[coll_name].count_documents({}) == 0 and seed:
                await db[coll_name].insert_many([dict(row) for row in seed])
                print(f"[OK] Seeded {coll_name} with {len(seed)} row(s)")
    except Exception as e:
        print(f"[WARN] Could not provision TPMS core collections: {e}")


async def close_mongo_connection():
    if db_connection.client:
        db_connection.client.close()
        print("Closed MongoDB connection")

def get_db():
    if db_connection.db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not available. Please ensure your IP is whitelisted in MongoDB Atlas dashboard."
        )
    return db_connection.db

def get_collection(name: str):
    db = get_db()
    return db[name]
