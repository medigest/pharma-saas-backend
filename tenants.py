# app/api/v1/tenants.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.user import UserResponse
from app.core.security import hash_password
from app.services.audit_service import log_action
from app.api.deps import get_current_user, subscription_required
import logging

router = APIRouter(prefix="/tenants", tags=["Tenants"])
logger = logging.getLogger(__name__)

# ------------------------------
# Créer un tenant + admin principal
# ------------------------------
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_tenant(
    data: dict,  # Idéalement un Pydantic schema TenantRegister à créer
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Crée un tenant (pharmacie) et son admin principal.
    """
    email_admin = data.get("email_admin")
    password_admin = data.get("password_admin")
    nom_pharmacie = data.get("nom_pharmacie")
    ville = data.get("ville")

    if not all([email_admin, password_admin, nom_pharmacie]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email admin, mot de passe et nom de la pharmacie sont requis"
        )

    # Vérifier si email admin existe
    existing = db.query(User).filter(User.email == email_admin).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email admin déjà utilisé"
        )

    # 1️⃣ Créer le tenant
    tenant = Tenant(
        nom_pharmacie=nom_pharmacie,
        ville=ville,
        email_admin=email_admin
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    logger.info(f"Tenant créé: {nom_pharmacie} ({tenant.id})")

    # 2️⃣ Créer l'admin principal
    admin_user = User(
        tenant_id=tenant.id,
        nom="Admin principal",
        email=email_admin.lower(),
        password_hash=hash_password(password_admin),
        role="admin",
        actif=True
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    logger.info(f"Admin principal créé: {admin_user.email}")

    # Log audit
    log_action(
        db=db,
        tenant_id=tenant.id,
        user_id=admin_user.id,
        action="TENANT_REGISTER",
        cible="tenant",
        description=f"Tenant créé: {nom_pharmacie}, admin: {email_admin}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "message": "Tenant et admin créés avec succès",
        "user": admin_user.to_dict(include_tenant=True),
        "login_url": "/auth/login"
    }


# ------------------------------
# Infos du tenant de l'utilisateur connecté
# ------------------------------
@router.get("/me")
def my_tenant(user: User = Depends(get_current_user)):
    """
    Retourne les infos du tenant de l'utilisateur connecté
    """
    tenant = user.tenant
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )

    return {
        "message": "Accès autorisé",
        "tenant": {
            "id": str(tenant.id),
            "nom_pharmacie": tenant.nom_pharmacie,
            "ville": tenant.ville,
            "email_admin": tenant.email_admin
        },
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role
        }
    }


# ------------------------------
# Route sécurisée SaaS
# ------------------------------
@router.get("/secure")
def secure_route(user: User = Depends(subscription_required)):
    return {"message": "Accès SaaS autorisé", "user": user.email}
