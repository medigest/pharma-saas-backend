# api/v1/subscriptions.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionCreate
from datetime import date
from app.services.subscription_service import get_active_subscription

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

@router.post("/")
def create_subscription(
    data: SubscriptionCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    sub = Subscription(
        tenant_id=user.tenant_id,
        prix=data.prix
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    return {"message": "Abonnement mensuel activé", "date_fin": sub.date_fin}

@router.get("/status")
def subscription_status(tenant_id: str):
    sub = get_active_subscription(tenant_id)

    if not sub or sub.end_date < date.today():
        return {
            "active": False,
            "mode": "READ_ONLY",
        }

    return {
        "active": True,
        "mode": "FULL",
    }