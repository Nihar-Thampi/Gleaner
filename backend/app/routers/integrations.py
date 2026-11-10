"""API keys and webhooks (admins only)."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import admin_only, get_owned, hash_api_key
from app.models import ApiKey, User, Webhook, WebhookDelivery, utcnow
from app.services import webhooks as webhook_service
from app.services.serializers import api_key_out, delivery_out, webhook_out

router = APIRouter(tags=["integrations"])


# ---- API keys ----

@router.get("/api-keys")
def list_keys(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.workspace_id == admin.workspace_id).order_by(ApiKey.created_at.desc())).all()
    return [api_key_out(k) for k in keys]


@router.post("/api-keys", status_code=201)
def create_key(body: schemas.ApiKeyIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    raw = "glk_" + secrets.token_urlsafe(32)
    key = ApiKey(workspace_id=admin.workspace_id, name=body.name.strip(), prefix=raw[:10], key_hash=hash_api_key(raw),
                 can_trigger_runs=body.can_trigger_runs, created_by_id=admin.id)
    db.add(key)
    db.commit()
    # The only time the full key is shown.
    return {**api_key_out(key), "key": raw}


@router.post("/api-keys/{key_id}/revoke")
def revoke_key(key_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    key = get_owned(db, ApiKey, key_id, admin.workspace_id)
    key.revoked_at = key.revoked_at or utcnow()
    db.commit()
    return api_key_out(key)


# ---- webhooks ----

def _last_delivery(db: Session, hook_id: str) -> WebhookDelivery | None:
    return db.scalar(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook_id).order_by(WebhookDelivery.id.desc()).limit(1))


@router.get("/webhooks")
def list_webhooks(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    hooks = db.scalars(select(Webhook).where(Webhook.workspace_id == admin.workspace_id).order_by(Webhook.created_at)).all()
    return {"events": webhook_service.EVENTS, "items": [webhook_out(h, _last_delivery(db, h.id)) for h in hooks]}


@router.post("/webhooks", status_code=201)
def create_webhook(body: schemas.WebhookIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    hook = Webhook(workspace_id=admin.workspace_id, url=body.url, events=sorted(set(body.events)), enabled=body.enabled,
                   secret="whsec_" + secrets.token_hex(24))
    db.add(hook)
    db.commit()
    return {**webhook_out(hook), "secret": hook.secret}


@router.patch("/webhooks/{hook_id}")
def update_webhook(hook_id: str, body: schemas.WebhookUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    hook = get_owned(db, Webhook, hook_id, admin.workspace_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("url"):
        hook.url = data["url"]
    if data.get("events"):
        hook.events = sorted(set(data["events"]))
    if data.get("enabled") is not None:
        hook.enabled = data["enabled"]
    db.commit()
    return webhook_out(hook, _last_delivery(db, hook.id))


@router.delete("/webhooks/{hook_id}", status_code=204)
def delete_webhook(hook_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Webhook, hook_id, admin.workspace_id))
    db.commit()


@router.post("/webhooks/{hook_id}/test")
async def test_webhook(hook_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    hook = get_owned(db, Webhook, hook_id, admin.workspace_id)
    delivery = await webhook_service.deliver(hook, "ping", {"message": "Test delivery from Gleaner", "webhook_id": hook.id})
    db.add(delivery)
    db.commit()
    return delivery_out(delivery)


@router.get("/webhooks/{hook_id}/deliveries")
def deliveries(hook_id: str, limit: int = Query(30, ge=1, le=200), admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    hook = get_owned(db, Webhook, hook_id, admin.workspace_id)
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id).order_by(WebhookDelivery.id.desc()).limit(limit)).all()
    return [delivery_out(d) for d in rows]
