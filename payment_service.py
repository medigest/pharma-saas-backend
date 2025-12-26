from sqlalchemy.orm import Session
from app.models.payment import Payment
from app.models.subscription import Subscription

def process_payment(db: Session, tenant_id, data):
    # 1️⃣ enregistrer paiement
    payment = Payment(
        tenant_id=tenant_id,
        montant=data.montant,
        moyen_paiement=data.moyen_paiement,
        reference=data.reference,
        statut="success"
    )
    db.add(payment)
    db.commit()

    # 2️⃣ activer abonnement mensuel (30 jours)
    subscription = Subscription(
        tenant_id=tenant_id,
        prix=data.montant
    )
    db.add(subscription)
    db.commit()

    return subscription
