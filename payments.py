#api/v1/payments.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.schemas.payment import PaymentCreate
from app.services.payment_service import process_payment

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.post("/")
def pay_subscription(
    data: PaymentCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    subscription = process_payment(db, user.tenant_id, data)

    return {
        "message": "Paiement réussi, abonnement activé",
        "date_fin": subscription.date_fin
    }
