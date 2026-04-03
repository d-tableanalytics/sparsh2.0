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

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role")
        company_id: Optional[str] = payload.get("company_id")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email, role=role, company_id=company_id)
    except JWTError:
        raise credentials_exception
    
    # Search staff first
    user = await get_collection("staff").find_one({"email": token_data.email})
    if not user:
        # Then learners
        user = await get_collection("learners").find_one({"email": token_data.email})
        
    if user is None:
        raise credentials_exception
    return user

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
