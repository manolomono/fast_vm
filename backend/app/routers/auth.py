"""Authentication & user management endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Request
import logging

from ..models import (
    LoginRequest, Token, UserInfo,
    ChangePasswordRequest, CreateUserRequest,
)
from ..auth import (
    authenticate_user, create_access_token,
    get_current_user, UserInfo as AuthUserInfo,
    verify_password, get_user, change_password,
    create_user, delete_user, list_users,
)
from ..audit import log_action

logger = logging.getLogger("fast_vm.routers.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(request: Request, login_data: LoginRequest):
    """Authenticate user and return JWT token"""
    client_ip = request.client.host if request.client else None
    user = authenticate_user(login_data.username, login_data.password)
    if not user:
        log_action(login_data.username, "login_failed", ip=client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(
        data={"sub": user.username, "is_admin": user.is_admin}
    )
    log_action(user.username, "login", ip=client_ip)
    return Token(access_token=access_token)


@router.post("/logout")
async def logout():
    """Logout endpoint (client should discard token)"""
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get current authenticated user info"""
    return UserInfo(username=current_user.username, is_admin=current_user.is_admin)


@router.post("/change-password")
async def change_user_password(
    data: ChangePasswordRequest,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Change current user's password"""
    user = get_user(current_user.username)
    if not user or not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        change_password(current_user.username, data.new_password)
        return {"success": True, "message": "Password changed successfully"}
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users")
async def get_users(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all users (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return list_users()


@router.post("/users")
async def create_new_user(
    data: CreateUserRequest,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a new user (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        create_user(data.username, data.password, data.is_admin)
        log_action(current_user.username, "create_user", "user", data.username, {"is_admin": data.is_admin})
        return {"success": True, "message": f"User '{data.username}' created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{username}")
async def remove_user(
    username: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Delete a user (admin only, cannot delete self)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    try:
        delete_user(username)
        log_action(current_user.username, "delete_user", "user", username)
        return {"success": True, "message": f"User '{username}' deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
