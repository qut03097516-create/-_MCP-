from fastapi import APIRouter, HTTPException, Response, Cookie, Header
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import re
import jwt
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.news_database import PVSystemDatabase

router = APIRouter()

# JWT 签名密钥只从环境变量读取；缺失时拒绝启动（fail-fast），
# 防止代码/压缩包中残留固定默认密钥导致 token 可伪造。
SECRET_KEY = os.environ.get("APP_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "缺少 APP_SECRET_KEY 环境变量。请生成随机密钥并配置：\n"
        "  powershell: $b=New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Fill($b); [Convert]::ToBase64String($b)\n"
        "  然后设置系统环境变量 APP_SECRET_KEY，不要写入代码或压缩包。"
    )
assert SECRET_KEY is not None  # type narrowing; guarded by raise above
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2MB

db = PVSystemDatabase()

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class AvatarUpdateRequest(BaseModel):
    avatar: str = ""


def _public_user(user: dict) -> dict:
    """对外暴露的用户字段（不含 password_hash）"""
    return {
        "id": user.get("id"),
        "username": user.get("username", ""),
        "email": user.get("email", "") or "",
        "role": user.get("role", "user"),
        "created_at": user.get("created_at", "") or "",
        "avatar": user.get("avatar", "") or "",
    }


def _resolve_token(
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> str:
    token = access_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    return token


def _current_user(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        user = db.get_user(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(user_id),
        "username": username,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response):
    user = db.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    access_token = create_access_token(user['id'], user['username'])
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        samesite="lax"
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=_public_user(user)
    )

@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest, response: Response):
    existing = db.get_user_by_username(request.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = db.create_user(request.username, request.password, request.email)
    if not user:
        raise HTTPException(status_code=500, detail="注册失败")

    access_token = create_access_token(user['id'], user['username'])
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        samesite="lax"
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=_public_user(user)
    )

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "退出登录成功"}

@router.get("/me")
async def get_current_user(token: Optional[str] = None, access_token: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    resolved = token or _resolve_token(access_token, authorization)
    user = _current_user(resolved)
    return _public_user(user)

@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    token: Optional[str] = None,
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    resolved = token or _resolve_token(access_token, authorization)
    user = _current_user(resolved)

    if not db.verify_password(request.old_password, user.get('password_hash', '')):
        return {"success": False, "message": "当前密码错误"}

    db.update_user_password(user['id'], request.new_password)
    return {"success": True, "message": "密码修改成功"}

@router.post("/avatar")
async def upload_avatar(
    body: AvatarUpdateRequest,
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """更新头像：JSON {avatar: dataURL}；空字符串表示清除"""
    resolved = _resolve_token(access_token, authorization)
    user = _current_user(resolved)

    avatar = (body.avatar or "").strip()
    if avatar:
        if not avatar.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="头像必须是图片 data URL")
        if not re.match(r"^data:image/(png|jpeg|jpg|webp);base64,", avatar, re.I):
            raise HTTPException(status_code=400, detail="仅支持 PNG/JPEG/WebP 图片")
        payload = avatar.split(",", 1)[-1] if "," in avatar else ""
        # base64 长度 ≈ 原始字节 * 4/3
        if len(payload) * 3 // 4 > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=400, detail="头像不能超过 2MB")

    db.update_user_avatar(user['id'], avatar)
    user = db.get_user(user['id']) or user
    user['avatar'] = avatar
    return {"success": True, "message": "头像已更新", "user": _public_user(user)}

@router.get("/users")
async def get_all_users(access_token: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    resolved = _resolve_token(access_token, authorization)
    current_user = _current_user(resolved)

    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="权限不足")

    users_df = db.get_all_users()
    users = users_df.to_dict('records') if not users_df.empty else []
    # 统一为 JSON 友好类型
    cleaned = []
    for u in users:
        cleaned.append({
            "id": int(u.get("id")),
            "username": u.get("username", ""),
            "email": u.get("email") or "",
            "role": u.get("role", "user"),
            "created_at": str(u.get("created_at") or ""),
            "last_login": str(u.get("last_login") or ""),
            "is_active": int(u.get("is_active") or 1),
            "avatar": u.get("avatar") or "",
        })
    return {
        "success": True,
        "data": cleaned,
        "total": len(cleaned),
        "admin_count": sum(1 for u in cleaned if u.get('role') == 'admin')
    }
