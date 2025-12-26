# app/core/security.py (version simplifiée)
from datetime import datetime, timedelta
from typing import Optional, List, Callable
from functools import wraps
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.models.user import User
from app.db.session import SessionLocal
from app.core.config import settings

# Gestion du mot de passe
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash d'un mot de passe"""
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe correspond à son hash"""
    return pwd_context.verify(password, hashed)

# JWT
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crée un token JWT"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# OAuth2 pour FastAPI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(SessionLocal)
) -> User:
    """Récupère l'utilisateur courant depuis le token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Impossible de valider les informations d'identification",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        
        if user_id is None or tenant_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception

    # Récupérer l'utilisateur depuis la base de données
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant_id,
        User.actif == True
    ).first()

    if user is None:
        raise credentials_exception
    
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Vérifie que l'utilisateur est actif"""
    if not current_user.actif:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur désactivé"
        )
    return current_user

# Système simple de permissions basé sur les rôles
ROLE_PERMISSIONS = {
    "super_admin": ["*"],  # Toutes les permissions
    "admin": ["*"],
    "pharmacien": ["ventes:create", "ventes:read", "ventes:update", "inventory:read", 
                   "inventory:update", "clients:read", "clients:create", "reports:read"],
    "gerant": ["ventes:create", "ventes:read", "ventes:update", "ventes:delete", 
               "inventory:*", "clients:*", "reports:*"],
    "vendeur": ["ventes:create", "ventes:read", "clients:read"],
    "caissier": ["ventes:create", "ventes:read"],
}

def has_permission(user_role: str, permission: str) -> bool:
    """Vérifie si un rôle a une permission"""
    permissions = ROLE_PERMISSIONS.get(user_role, [])
    
    # Si l'utilisateur a "*", il a toutes les permissions
    if "*" in permissions:
        return True
    
    # Vérifier la permission exacte ou par module
    if permission in permissions:
        return True
    
    # Vérifier les permissions de module (ex: "ventes:*")
    module = permission.split(":")[0] + ":*"
    return module in permissions

def require_permission(permission_code: str):
    """Décorateur pour vérifier les permissions"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Trouver l'utilisateur dans les arguments
            current_user = None
            for arg in kwargs.values():
                if isinstance(arg, User):
                    current_user = arg
                    break
            
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Utilisateur non authentifié"
                )
            
            # Vérifier la permission
            if not has_permission(current_user.role, permission_code):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{permission_code}' requise. Rôle: {current_user.role}"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

def require_role(allowed_roles: List[str]):
    """Décorateur pour vérifier le rôle"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Trouver l'utilisateur dans les arguments
            current_user = None
            for arg in kwargs.values():
                if isinstance(arg, User):
                    current_user = arg
                    break
            
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Utilisateur non authentifié"
                )
            
            # Vérifier le rôle
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Rôles autorisés: {allowed_roles}. Votre rôle: {current_user.role}"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator