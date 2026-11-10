"""Workspace settings and team members (admins only, except reading the workspace)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import hash_password
from app.db import get_db
from app.deps import admin_only, get_current_user
from app.models import User
from app.services.serializers import user_out, workspace_out

router = APIRouter(tags=["team"])


@router.get("/workspace")
def get_workspace(user: User = Depends(get_current_user)):
    return workspace_out(user.workspace)


@router.patch("/workspace")
def update_workspace(body: schemas.WorkspaceUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    ws = admin.workspace
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(ws, key, value)
    db.commit()
    return workspace_out(ws)


@router.get("/users")
def list_users(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.workspace_id == admin.workspace_id).order_by(User.full_name)).all()
    return [user_out(u) for u in users]


@router.post("/users", status_code=201)
def create_user(body: schemas.UserIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    user = User(workspace_id=admin.workspace_id, email=body.email.lower(), full_name=body.full_name.strip(),
                role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already in use.")
    return user_out(user)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: schemas.UserUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None or user.workspace_id != admin.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    data = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (data.get("is_active") is False or data.get("role", "admin") != "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove your own admin access.")
    if data.get("password"):
        user.password_hash = hash_password(data.pop("password"))
    data.pop("password", None)
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    return user_out(user)
