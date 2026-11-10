from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.core.security import create_token, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.serializers import user_out, workspace_out

router = APIRouter(prefix="/auth", tags=["auth"])


def me_payload(user: User) -> dict:
    return {"user": user_out(user), "workspace": workspace_out(user.workspace)}


@router.post("/login")
def login(body: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    return {**me_payload(user), "token": create_token(user.id, user.workspace_id)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return me_payload(user)
