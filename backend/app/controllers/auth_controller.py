from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.config.settings import settings
from app.db.mongodb import get_collection
from app.models.auth import TokenData
from app.models.user import UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def get_user_from_token(token: str) -> Optional[dict]:
    """Decode a JWT and resolve the user doc (staff first, then learners).
    Returns None on any failure. Used where the token can't come from the
    Authorization header — e.g. the SSE stream endpoint reads it from a query
    param because EventSource can't set headers."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None

    user = await get_collection("staff").find_one({"email": email})
    if user:
        user["_source_collection"] = "staff"
    else:
        user = await get_collection("learners").find_one({"email": email})
        if user:
            user["_source_collection"] = "learners"
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = await get_user_from_token(token)
    if user is None:
        raise credentials_exception
    return user


# ─── Task Management access gate ───
# Internal = users in the `staff` collection (tag="staff"): superadmin/admin and any future
# staff-side role. Internal users always have the module.
#
# Client-side users (learners collection: clientadmin/clientuser) get the module only when
# their company's Delegation toggle is ON (Company Details ▸ Delegation On/Off, stored as
# `delegation_enabled` on the company). The legacy per-user
# `permissions.tasks.access_task_management` override still works for one-off grants.
INTERNAL_ROLES = {"superadmin", "admin", "coach", "staff"}
CLIENT_ROLES = {"clientadmin", "clientuser"}
TASK_ACCESS_DENIED_MESSAGE = "Task Management is only available for Sparsh internal teams."
DELEGATION_DISABLED_MESSAGE = (
    "The Delegation module is not enabled for your company. "
    "Please contact your administrator."
)


def is_internal_user(user: dict) -> bool:
    if not user:
        return False
    if user.get("role") == "superadmin":
        return True
    # Explicit override so an admin can grant a specific client user access.
    if user.get("permissions", {}).get("tasks", {}).get("access_task_management"):
        return True
    src = user.get("_source_collection")
    if src == "staff":
        return True
    if src == "learners":
        return False
    # Fallback when the collection wasn't stamped (defensive): use tag, then role.
    if user.get("tag") == "staff":
        return True
    if user.get("tag") == "learner":
        return False
    return user.get("role") in INTERNAL_ROLES


def is_client_side_user(user: dict) -> bool:
    """A company (client) user rather than a Sparsh internal user."""
    if not user:
        return False
    src = user.get("_source_collection")
    if src == "learners":
        return True
    if src == "staff":
        return False
    if user.get("tag") == "learner":
        return True
    return (user.get("role") or "").lower() in CLIENT_ROLES


async def is_company_delegation_enabled(company_id) -> bool:
    """Whether the Task & Delegation module is switched on for a client company.

    Mirrors utils/orm_utils.is_orm_enabled, with one deliberate difference: a MISSING flag
    means OFF. Delegation was internal-only before this toggle existed, so an existing
    company must be explicitly enabled by a Sparsh admin rather than silently gaining
    access to a module it never had."""
    if not company_id:
        return False
    from bson import ObjectId
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("delegation_enabled", False))


async def has_task_access(user: dict) -> bool:
    """Async access check used everywhere the Task & Delegation module is gated:
    internal Sparsh users always, client-side users only while their company's
    Delegation toggle is ON."""
    if is_internal_user(user):
        return True
    return await is_company_delegation_enabled(user.get("company_id"))


async def require_task_access(current_user: dict = Depends(get_current_user)):
    """Dependency that 403s anyone without Task & Delegation access. Returns the user so
    endpoints that swap `Depends(get_current_user)` -> `Depends(require_task_access)`
    still receive it."""
    if await has_task_access(current_user):
        return current_user
    raise HTTPException(
        status_code=403,
        detail=DELEGATION_DISABLED_MESSAGE if is_client_side_user(current_user) else TASK_ACCESS_DENIED_MESSAGE,
    )


TASK_RECIPIENT_DENIED_MESSAGE = (
    "Task and Delegation module is only for Sparsh internal users. "
    "Client-side users cannot be assigned or added in loop."
)

COMPANY_RECIPIENT_DENIED_MESSAGE = (
    "Tasks can only be assigned to — or shared in loop with — users of your own company."
)


def recipient_denied_message(actor: dict) -> str:
    """The right rejection message for whoever is creating/editing the task."""
    return COMPANY_RECIPIENT_DENIED_MESSAGE if is_client_side_user(actor) else TASK_RECIPIENT_DENIED_MESSAGE


async def get_ineligible_recipient_ids(actor: dict, user_ids) -> list:
    """Recipients (assignees + in-loop members) this actor is not allowed to put on a task.

    - Internal Sparsh actor → recipients must be internal staff (unchanged rule).
    - Client-side actor (company with Delegation ON) → recipients must be users of the SAME
      company, so a company can only delegate within itself and never reaches — or sees —
      the internal Sparsh directory.
    """
    from bson import ObjectId
    ids = [str(i) for i in (user_ids or []) if i]
    if not ids:
        return []
    if not is_client_side_user(actor):
        return await get_non_internal_user_ids(ids)

    company_id = actor.get("company_id")
    if not company_id:
        return ids
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except Exception:
            pass
    eligible = set()
    cursor = get_collection("learners").find(
        {"_id": {"$in": oids}, "company_id": str(company_id)}, {"_id": 1}
    )
    async for u in cursor:
        eligible.add(str(u["_id"]))
    return [i for i in ids if i not in eligible]


async def get_non_internal_user_ids(user_ids) -> list:
    """Given a list of user id strings (task assignees + watchers), return those that are
    NOT internal Sparsh users. Internal = present in the `staff` collection. Any id not
    found in staff (i.e. a learner / client-side user, or a bogus id) is treated as
    non-internal and returned so the caller can reject it."""
    from bson import ObjectId
    ids = [str(i) for i in (user_ids or []) if i]
    if not ids:
        return []
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except Exception:
            pass
    internal = set()
    cursor = get_collection("staff").find({"_id": {"$in": oids}}, {"_id": 1})
    async for u in cursor:
        internal.add(str(u["_id"]))
    return [i for i in ids if i not in internal]

async def get_current_active_user(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def check_role(required_roles: List[str]):
    async def role_checker(current_user: dict = Depends(get_current_active_user)):
        if current_user.get("role") not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have enough permissions"
            )
        return current_user
    return role_checker

def check_permission(module: str, action: str):
    async def permission_checker(current_user: dict = Depends(get_current_active_user)):
        # SuperAdmin has global access
        if current_user.get("role") == "superadmin":
            return current_user
        
        # Fetch role permissions
        role_name = current_user.get("role")
        roles_collection = get_collection("roles")
        role = await roles_collection.find_one({"name": role_name})
        
        if not role:
            # Fallback for default roles or missing definitions
            raise HTTPException(status_code=403, detail="Role permissions not defined")
        
        for perm in role.get("permissions", []):
            if perm.get("module") == module and action in perm.get("actions", []):
                return current_user
                
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {module}:{action}"
        )
    return permission_checker
