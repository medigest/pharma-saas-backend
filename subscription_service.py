# app/services/subscription_service.py
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.subscription import Subscription

def is_subscription_active(db: Session, tenant_id):
    """
    Vérifie si l'abonnement est actif pour un tenant
    Ancien nom de fonction - à garder pour compatibilité
    """
    subscription = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.date_fin.desc())
        .first()
    )

    if not subscription:
        return False

    if subscription.date_fin < datetime.utcnow():
        subscription.statut = "expirée"
        db.commit()
        return False

    return subscription.statut == "active"

def get_active_subscription(db: Session, tenant_id):
    """
    Récupère l'abonnement actif pour un tenant
    Version corrigée qui accepte la session DB
    """
    subscription = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.date_fin.desc())
        .first()
    )
    
    return subscription

def check_subscription_status(db: Session, tenant_id: str) -> bool:
    """
    Vérifie le statut de l'abonnement
    Retourne True si actif, False sinon
    """
    subscription = get_active_subscription(db, tenant_id)
    
    if not subscription:
        return False
    
    # Vérifier si la date de fin est passée
    if subscription.date_fin < datetime.utcnow():
        # Mettre à jour le statut
        subscription.statut = "expirée"
        db.commit()
        return False
    
    return subscription.statut == "active"