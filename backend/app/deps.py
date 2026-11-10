"""Authentication (user sessions and API keys) and workspace scoping."""
import hashlib

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db import get_db
from app.models import ApiKey, Role, User, utcnow

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again.")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active or user.workspace_id != payload.get("wid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    return user


def require_roles(*roles: Role):
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do that.")
        return user

    return check


EDIT = (Role.admin, Role.editor)
can_edit = require_roles(*EDIT)
admin_only = require_roles(Role.admin)


def get_owned(db: Session, model, obj_id: str, workspace_id: str):
    """Load a row from this workspace, or 404 (never 403: don't reveal it exists)."""
    obj = db.get(model, obj_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return obj


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_api_key(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Send your API key in the X-API-Key header.")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(x_api_key)))
    if key is None or key.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key.")
    key.last_used_at = utcnow()
    db.commit()
    return key
