import asyncio
import motor.motor_asyncio
import certifi
import ssl
from app.config.settings import settings

async def migrate():
    print(f"Connecting to {settings.DATABASE_NAME}...")
    
    # Secure connection configuration
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where()
    )
    db = client[settings.DATABASE_NAME]
    
    users_col = db["users"]
    staff_col = db["staff"]
    learners_col = db["learners"]
    
    STAFF_ROLES = ["superadmin", "admin", "coach"]
    
    count = 0
    # Use to_list(1000) to avoid keep alive issues on slow migrations
    users = await users_col.find({}).to_list(1000)
    
    for user in users:
        role = str(user.get("role", "")).lower()
        target = staff_col if role in STAFF_ROLES else learners_col
        
        if not await target.find_one({"email": user["email"]}):
            await target.insert_one(user)
            print(f"Moved {user['email']} -> {target.name}")
            count += 1
            
    print(f"\nMigration Success! Users migrated: {count}")
    client.close()

if __name__ == "__main__":
    asyncio.run(migrate())
