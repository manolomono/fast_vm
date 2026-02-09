"""
Authentication module for Fast VM
Handles JWT token creation/verification and user management
Uses SQLite for user persistence (via database module)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel
import logging

from app.database import (
    db_get_user, db_list_users, db_create_user,
    db_delete_user, db_change_password, migrate_users_from_json,
)

logger = logging.getLogger("fast_vm.auth")

# Configuration
_default_secret = "fast-vm-secret-key-change-in-production"
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _default_secret)
if os.environ.get("FASTVM_PRODUCTION") and SECRET_KEY == _default_secret:
    raise RuntimeError("JWT_SECRET_KEY must be set in production. Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"")
if SECRET_KEY == _default_secret:
    logger.warning("Using default JWT secret key. Set JWT_SECRET_KEY env var for production.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Security scheme
security = HTTPBearer()

# Legacy users.json path (for migration)
USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")


# Models
class User(BaseModel):
    username: str
    hashed_password: str
    is_admin: bool = True


class UserInfo(BaseModel):
    username: str
    is_admin: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Password functions
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


# Token functions
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify a JWT token and return its payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# User management functions (SQLite-backed)
def get_user(username: str) -> Optional[User]:
    """Get a user by username"""
    data = db_get_user(username)
    if data:
        return User(**data)
    return None


def authenticate_user(username: str, password: str) -> Optional[User]:
    """Authenticate a user with username and password"""
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(username: str, password: str, is_admin: bool = False) -> User:
    """Create a new user"""
    hashed = hash_password(password)
    data = db_create_user(username, hashed, is_admin)
    return User(**data)


def delete_user(username: str) -> bool:
    """Delete a user"""
    return db_delete_user(username)


def change_password(username: str, new_password: str) -> bool:
    """Change a user's password"""
    hashed = hash_password(new_password)
    return db_change_password(username, hashed)


def list_users() -> list:
    """List all users (without password hashes)"""
    return db_list_users()


def create_default_user():
    """Create default admin user if no users exist"""
    # First, migrate any existing users.json
    migrate_users_from_json(USERS_FILE)

    # Then create default admin if no users exist
    users = db_list_users()
    if not users:
        hashed = hash_password("admin")
        db_create_user("admin", hashed, is_admin=True)
        logger.info("Created default admin user (username: admin, password: admin)")


# FastAPI dependency for getting current user
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserInfo:
    """Dependency to get the current authenticated user from JWT token"""
    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user(username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserInfo(username=user.username, is_admin=user.is_admin)
