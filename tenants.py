# app/api/routes/tenants.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime, timedelta

from app.db.session import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate
from app.schemas.user import UserCreate
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings

router = APIRouter(prefix="/admin/tenants", tags=["Administration"])

@router.post("/", response_model=TenantResponse)
def create_tenant(
    tenant_data: TenantCreate,
    admin_user: UserCreate,
    db: Session = Depends(get_db)
):
    """Crée un nouveau tenant avec son administrateur"""
    
    # Vérifier si l'email du tenant existe déjà
    existing_tenant = db.query(Tenant).filter(Tenant.email == tenant_data.email).first()
    if existing_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email déjà utilisé"
        )
    
    # Vérifier si le nom d'utilisateur existe déjà
    existing_user = db.query(User).filter(User.username == admin_user.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nom d'utilisateur déjà utilisé"
        )
    
    # Créer le tenant
    tenant = Tenant(
        **tenant_data.dict(),
        api_key=str(uuid.uuid4()),
        date_debut_abonnement=datetime.utcnow(),
        date_fin_essai=datetime.utcnow() + timedelta(days=30)  # Essai gratuit de 30 jours
    )
    db.add(tenant)
    db.flush()  # Pour obtenir l'ID du tenant
    
    # Créer l'utilisateur admin
    admin = User(
        tenant_id=tenant.id,
        username=admin_user.username,
        email=admin_user.email,
        nom_complet=admin_user.nom_complet,
        role="admin",
        is_active=True,
        is_verified=True
    )
    admin.set_password(admin_user.password)
    db.add(admin)
    
    db.commit()
    db.refresh(tenant)
    
    # Créer un token d'accès pour l'admin
    access_token = create_access_token(
        data={
            "sub": str(admin.id),
            "tenant_id": str(tenant.id),
            "role": admin.role
        }
    )
    
    return {
        "tenant": tenant,
        "admin_token": access_token,
        "api_key": tenant.api_key
    }

@router.get("/", response_model=List[TenantResponse])
def list_tenants(
    skip: int = 0,
    limit: int = 100,
    statut: str = None,
    db: Session = Depends(get_db)
):
    """Liste tous les tenants (admin seulement)"""
    query = db.query(Tenant)
    
    if statut:
        query = query.filter(Tenant.statut == statut)
    
    return query.order_by(Tenant.date_creation.desc()).offset(skip).limit(limit).all()

@router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Récupère un tenant spécifique"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )
    return tenant

@router.put("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: uuid.UUID,
    tenant_update: TenantUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )
    
    for field, value in tenant_update.dict(exclude_unset=True).items():
        setattr(tenant, field, value)
    
    db.commit()
    db.refresh(tenant)
    
    return tenant

@router.post("/{tenant_id}/suspendre")
def suspend_tenant(
    tenant_id: uuid.UUID,
    raison: str,
    db: Session = Depends(get_db)
):
    """Suspend un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )
    
    tenant.statut = "suspendu"
    tenant.config["raison_suspension"] = raison
    db.commit()
    
    return {"message": "Tenant suspendu"}

@router.post("/{tenant_id}/reactiver")
def reactivate_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Réactive un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )
    
    tenant.statut = "actif"
    if "raison_suspension" in tenant.config:
        del tenant.config["raison_suspension"]
    
    db.commit()
    
    return {"message": "Tenant réactivé"}

@router.get("/{tenant_id}/statistiques")
def get_tenant_stats(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Récupère les statistiques d'un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trouvé"
        )
    
    # Statistiques (exemples)
    total_utilisateurs = db.query(User).filter(User.tenant_id == tenant_id).count()
    # Ajouter d'autres stats: produits, ventes, etc.
    
    return {
        "tenant": tenant.nom_pharmacie,
        "statut": tenant.statut,
        "date_creation": tenant.date_creation,
        "total_utilisateurs": total_utilisateurs,
        "abonnement": {
            "plan": tenant.plan_abonnement,
            "date_fin_essai": tenant.date_fin_essai,
            "jours_restants": (tenant.date_fin_essai - datetime.utcnow()).days if tenant.date_fin_essai else None
        }
    }