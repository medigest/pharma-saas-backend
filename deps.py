# app/api/deps.py

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID

from app.db.session import get_db
from app.models.user import User
from app.models.tenant import Tenant
from app.core.config import settings
from app.services.subscription_service import is_subscription_active

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ======================================================
# AUTHENTIFICATION UTILISATEUR
# ======================================================

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Récupère l'utilisateur courant depuis le token JWT"""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise credentials_exception

        user_uuid = UUID(user_id)

    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Vérifie que l'utilisateur est actif"""

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur inactif ou suspendu"
        )

    return current_user


# ======================================================
# TENANT
# ======================================================

def get_current_tenant(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Tenant:
    """
    Récupère le tenant associé à l'utilisateur courant
    """
    # Si l'utilisateur a un tenant_id, l'utiliser
    if not current_user.tenant_id:
        # Pour les comptes admin ou système, on pourrait avoir une logique différente
        raise HTTPException(
            status_code=400,
            detail="Utilisateur non associé à un tenant"
        )
    
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Tenant introuvable"
        )
    
    if tenant.status not in ("active", "trial"):
        raise HTTPException(
            status_code=403,
            detail=f"Tenant {tenant.status} – accès refusé"
        )
    
    return tenant

# ======================================================
# ABONNEMENT
# ======================================================

def subscription_required(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
) -> Tenant:
    """Vérifie que l'abonnement du tenant est actif"""

    if not is_subscription_active(db, tenant.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Abonnement expiré ou inactif"
        )

    return tenant


# ======================================================
# ROLES & PERMISSIONS
# ======================================================

def require_role(required_roles: List[str]):
    """Vérifie le rôle de l'utilisateur"""

    def role_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:

        if current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle requis : {', '.join(required_roles)}"
            )

        return current_user

    return role_checker


def require_permission(permission: str):
    """Vérifie les permissions de l'utilisateur"""

    def permission_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:

        permission_map = {
            "admin": [
                "ventes:create", "ventes:read", "ventes:update",
                "ventes:delete", "ventes:stats", "ventes:export",
                "ventes:cancel"
            ],
            "gerant": [
                "ventes:create", "ventes:read", "ventes:update",
                "ventes:stats", "ventes:export", "ventes:cancel"
            ],
            "vendeur": ["ventes:create", "ventes:read"],
            "caissier": ["ventes:create", "ventes:read"],
            "superviseur": ["ventes:read", "ventes:stats", "ventes:export"]
        }

        user_permissions = permission_map.get(current_user.role, [])

        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission requise : {permission}"
            )

        return current_user

    return permission_checker


# ======================================================
# UTILISATEUR OPTIONNEL (PUBLIC / STATS)
# ======================================================

def get_optional_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Retourne l'utilisateur courant si token présent"""

    if not token:
        return None

    try:
        return get_current_user(token, db)
    except HTTPException:
        return None


# ======================================================
# EXPORTS
# ======================================================

__all__ = [
    "get_db",
    "get_current_user",
    "get_current_active_user",
    "get_current_tenant",
    "subscription_required",
    "require_role",
    "require_permission",
    "get_optional_current_user",
    "oauth2_scheme"
]

# app/api/deps.py (ajouter cette fonction)

def get_tenant_id_from_request(request: Request) -> Optional[str]:
    """
    Récupère le tenant ID de la requête de manière flexible
    """
    # 1. Essayer depuis les headers
    tenant_id = request.headers.get("X-Tenant-ID")
    
    # 2. Essayer depuis le token JWT (pour les routes authentifiées)
    if not tenant_id:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(
                    token, 
                    settings.SECRET_KEY, 
                    algorithms=[settings.ALGORITHM],
                    options={"verify_signature": False}  # Juste pour lire le payload
                )
                tenant_id = payload.get("tenant_id")
            except Exception:
                pass
    
    # 3. Essayer depuis l'état de la requête (si middleware a déjà ajouté)
    if not tenant_id and hasattr(request.state, "tenant_id"):
        tenant_id = request.state.tenant_id
    
    return tenant_id


def get_current_tenant_with_fallback(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    request: Request = None
) -> Tenant:
    """
    Version plus flexible qui peut récupérer le tenant de plusieurs sources
    """
    # Si l'utilisateur a déjà un tenant_id, l'utiliser
    if current_user.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        if tenant:
            return tenant
    
    # Sinon, essayer de récupérer depuis la requête
    if request:
        tenant_id = get_tenant_id_from_request(request)
        if tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                return tenant
    
    # Si on arrive ici, lever une exception
    raise HTTPException(
        status_code=400,
        detail="Tenant non spécifié et non trouvé dans le profil utilisateur"
    )