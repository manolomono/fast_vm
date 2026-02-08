"""
Authentication module for Fast VM
Handles JWT token creation/verification and user management
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel
import logging

logger = logging.getLogger("fast_vm.auth")

# Configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fast-vm-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Security scheme
security = HTTPBearer()

# Users file path
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


# User management functions
def load_users() -> dict:
    """Load users from JSON file"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_users(users: dict) -> None:
    """Save users to JSON file"""
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def get_user(username: str) -> Optional[User]:
    """Get a user by username"""
    users = load_users()
    if username in users:
        return User(**users[username])
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
    users = load_users()
    if username in users:
        raise ValueError(f"User '{username}' already exists")
    users[username] = {
        "username": username,
        "hashed_password": hash_password(password),
        "is_admin": is_admin
    }
    save_users(users)
    return User(**users[username])


def delete_user(username: str) -> bool:
    """Delete a user"""
    users = load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    del users[username]
    save_users(users)
    return True


def change_password(username: str, new_password: str) -> bool:
    """Change a user's password"""
    users = load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    users[username]["hashed_password"] = hash_password(new_password)
    save_users(users)
    return True


def list_users() -> list:
    """List all users (without password hashes)"""
    users = load_users()
    return [{"username": u["username"], "is_admin": u.get("is_admin", False)} for u in users.values()]


def create_default_user():
    """Create default admin user if no users exist"""
    users = load_users()
    if not users:
        users["admin"] = {
            "username": "admin",
            "hashed_password": hash_password("admin"),
            "is_admin": True
        }
        save_users(users)
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


# Initialize default user on module load
create_default_user()
