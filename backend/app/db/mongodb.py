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
        print(f"[OK] Successfully connected to MongoDB Atlas (Database: {settings.DATABASE_NAME})")
        
    except Exception as e:
        print(f"[FAILED] connect to MongoDB: {e}")
        db_connection.db = None

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
