import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from app.config.settings import settings
from app.controllers.auth_controller import get_password_hash

async def seed_data():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    
    # 1. Seed Roles and Permissions
    roles_collection = db.roles
    
    default_roles = [
        {
            "name": "superadmin",
            "description": "Full system control",
            "scope": "global",
            "permissions": [
                {"module": "Companies", "actions": ["create", "read", "update", "delete", "manage"], "scope": "global"},
                {"module": "Users", "actions": ["create", "read", "update", "delete", "manage"], "scope": "global"},
                {"module": "LMS", "actions": ["create", "read", "update", "delete", "manage"], "scope": "global"},
                {"module": "Reports", "actions": ["read", "export"], "scope": "global"}
            ]
        },
        {
            "name": "clientadmin",
            "description": "Full control within their company",
            "scope": "company",
            "permissions": [
                {"module": "Users", "actions": ["create", "read", "update", "delete"], "scope": "company"},
                {"module": "Tasks", "actions": ["create", "read", "update", "assign", "delete"], "scope": "company"},
                {"module": "LMS", "actions": ["read"], "scope": "company"},
                {"module": "Reports", "actions": ["read"], "scope": "company"}
            ]
        },
        {
            "name": "clientdoer",
            "description": "Individual learner access",
            "scope": "personal",
            "permissions": [
                {"module": "Tasks", "actions": ["read", "update"], "scope": "personal"},
                {"module": "LMS", "actions": ["read"], "scope": "personal"}
            ]
        }
    ]

    for role in default_roles:
        await roles_collection.update_one(
            {"name": role["name"]},
            {"$set": role},
            upsert=True
        )
    print("Seed roles and permissions created/updated.")

    # 2. Seed SuperAdmin User
    users_collection = db.users
    admin_email = "admin@example.com"
    existing_admin = await users_collection.find_one({"email": admin_email})
    
    if not existing_admin:
        hashed_password = get_password_hash("password123")
        admin_user = {
            "email": admin_email,
            "full_name": "Super Admin",
            "password": hashed_password,
            "role": "superadmin",
            "company_id": None, # SuperAdmin is global
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        await users_collection.insert_one(admin_user)
        print(f"Created seed SuperAdmin: {admin_email} / password123")
    else:
        # Update existing admin to be global
        await users_collection.update_one(
            {"email": admin_email},
            {"$set": {"role": "superadmin", "company_id": None}}
        )
        print(f"Global SuperAdmin {admin_email} verified.")

    client.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
