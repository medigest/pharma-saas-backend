# app/api/v1/users.py
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from typing import List
import logging
import traceback
import sys

from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserProfile
from app.core.security import hash_password
from app.api.v1.auth import get_current_user
from app.services.audit_service import log_action

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

# =========================
# CREATE USER
# =========================
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crée un utilisateur pour le tenant de l'admin connecté.
    """
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Accès refusé")

    # Vérifier email unique dans le tenant
    existing_user = db.query(User).filter(
        User.email == user_data.email.lower().strip(),
        User.tenant_id == current_user.tenant_id
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà utilisé dans votre pharmacie")

    # Création utilisateur
    new_user = User(
        tenant_id=current_user.tenant_id,
        nom=user_data.nom_complet,
        email=user_data.email.lower().strip(),
        password_hash=hash_password(user_data.password),
        role=user_data.role.value,
        actif=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Audit log
    log_action(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="CREATE_USER",
        cible="user",
        description=f"Création utilisateur: {new_user.email} (role={new_user.role})",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "message": "Utilisateur créé avec succès",
        "user": new_user.to_dict(include_tenant=False)
    }


# =========================
# UPDATE USER
# =========================
@router.put("/{user_id}", status_code=status.HTTP_200_OK)
def update_user(
    user_id: str,
    user_data: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Accès refusé")

    user = db.query(User).filter(User.id == user_id, User.tenant_id == current_user.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    for field, value in user_data.dict(exclude_unset=True).items():
        if field == "password":
            setattr(user, "password_hash", hash_password(value))
        else:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="UPDATE_USER",
        cible="user",
        description=f"Mise à jour utilisateur: {user.email}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    return {"message": "Utilisateur mis à jour", "user": user.to_dict(include_tenant=False)}


# =========================
# ACTIVER / DÉSACTIVER USER
# =========================
@router.patch("/{user_id}/toggle", status_code=status.HTTP_200_OK)
def toggle_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Accès refusé")

    user = db.query(User).filter(User.id == user_id, User.tenant_id == current_user.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    user.actif = not user.actif
    db.commit()
    db.refresh(user)

    action = "ACTIVATE_USER" if user.actif else "DEACTIVATE_USER"
    log_action(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=action,
        cible="user",
        description=f"{action} pour {user.email}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    return {"message": f"Utilisateur {'activé' if user.actif else 'désactivé'}", "user": user.to_dict(include_tenant=False)}


# =========================
# LIST USERS PAGINATED
# =========================
@router.get("/", status_code=status.HTTP_200_OK, response_model=List[UserProfile])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Accès refusé")

    offset = (page - 1) * limit
    users_query = db.query(User).filter(User.tenant_id == current_user.tenant_id)
    users = users_query.offset(offset).limit(limit).all()
    return [u.to_dict(include_tenant=False) for u in users]


# =========================
# GET USER DETAILS
# =========================
@router.get("/{user_id}", status_code=status.HTTP_200_OK, response_model=UserProfile)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user = db.query(User).filter(User.id == user_id, User.tenant_id == current_user.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user.to_dict(include_tenant=False)
