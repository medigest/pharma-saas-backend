# app/api/v1/auth.py
from datetime import datetime, timedelta
import logging
import random
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.pharmacy import Pharmacy
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_pharmacy import UserPharmacy
from app.services.notification_service import send_sms, send_whatsapp
from app.services.subscription_service import check_subscription_status

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger(__name__)

# Constantes
OTP_EXPIRATION_MIN = 5
RESET_EXPIRATION_MIN = 10
MAX_LOGIN_ATTEMPTS = 5
LOCK_MIN = 15

# Cache pour rate limiting
_rate_limiter_cache = {}


# =========================
# MODÈLES DE DONNÉES (Pydantic Schemas)
# =========================
class TenantRegisterSchema(BaseModel):
    email: EmailStr
    password: str
    confirm_password: Optional[str] = None
    nom_complet: str
    nom_pharmacie: str
    ville: str
    telephone: str
    type_pharmacie: str = "officine"
    pays: str = "RDC"

    @field_validator("password")
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Mot de passe trop court (8 caractères minimum)")
        if len(v.encode('utf-8')) > 72:
            raise ValueError("Mot de passe trop long (72 caractères maximum)")
        if not any(c.isupper() for c in v):
            raise ValueError("Au moins une majuscule requise")
        if not any(c.islower() for c in v):
            raise ValueError("Au moins une minuscule requise")
        if not any(c.isdigit() for c in v):
            raise ValueError("Au moins un chiffre requis")
        return v
    
    @field_validator("telephone")
    def validate_phone(cls, v: str) -> str:
        v = re.sub(r'\D', '', v)
        
        if len(v) < 9:
            raise ValueError("Numéro de téléphone invalide (minimum 9 chiffres)")
        
        if len(v) == 9:
            return v
        elif len(v) == 11 and v.startswith('243'):
            return v
        elif len(v) == 12 and v.startswith('243'):
            return v[1:] if v[0] == '0' else v
        else:
            return v

    @model_validator(mode="after")
    def check_passwords(cls, model):
        if model.confirm_password and model.password != model.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas")
        return model


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class ResetRequestSchema(BaseModel):
    email: EmailStr


class ResetConfirmSchema(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class VerifySMSSchema(BaseModel):
    email: EmailStr
    code: str


class ResendSMSSchema(BaseModel):
    email: EmailStr


# =========================
# FONCTIONS UTILITAIRES
# =========================
def format_phone_for_twilio(phone: str) -> str:
    """Formate un numéro de téléphone pour Twilio (format E.164)"""
    if not phone:
        return phone
    
    phone = re.sub(r'\D', '', phone)
    
    if not phone:
        return phone
    
    if phone.startswith('0'):
        phone = phone[1:]
    
    if len(phone) == 9:
        return f"+243{phone}"
    elif len(phone) == 11 and phone.startswith('243'):
        return f"+{phone}"
    elif phone.startswith('+'):
        return phone
    else:
        return f"+{phone}"


def rate_limit_check(key: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
    """Vérifie si une clé a dépassé la limite de tentatives"""
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_seconds)
    
    if key in _rate_limiter_cache:
        _rate_limiter_cache[key] = [
            timestamp for timestamp in _rate_limiter_cache[key]
            if timestamp > window_start
        ]
    
    attempts = _rate_limiter_cache.get(key, [])
    if len(attempts) >= max_attempts:
        logger.warning(f"Rate limit atteint pour {key}")
        return False
    
    attempts.append(now)
    _rate_limiter_cache[key] = attempts[-max_attempts:]
    return True


def generate_otp() -> str:
    """Génère un code OTP à 6 chiffres"""
    return str(random.randint(100000, 999999))


def generate_tenant_code(nom_pharmacie: str) -> str:
    """Génère un code unique pour un tenant"""
    prefix = nom_pharmacie[:3].upper().replace(' ', '')
    if len(prefix) < 3:
        prefix = prefix + 'PH'
    random_suffix = str(random.randint(100, 999))
    return f"{prefix}{random_suffix}"


def generate_slug(nom_pharmacie: str) -> str:
    """Génère un slug à partir du nom de la pharmacie"""
    slug = nom_pharmacie.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def is_subscription_active(db: Session, tenant_id: str) -> bool:
    """Vérifie si l'abonnement est actif pour un tenant donné"""
    try:
        return check_subscription_status(db, tenant_id)
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de l'abonnement: {e}")
        return False


# =========================
# ENDPOINTS D'AUTHENTIFICATION
# =========================
@router.post("/tenants/register", status_code=201)
def register_tenant(data: TenantRegisterSchema, db: Session = Depends(get_db)):
    """Inscription d'un nouveau tenant (pharmacie)"""
    existing_user = db.query(User).filter(User.email == data.email.lower()).first()
    if existing_user:
        raise HTTPException(409, "Email déjà utilisé")

    if len(data.password.encode('utf-8')) > 72:
        raise HTTPException(400, "Mot de passe trop long (maximum 72 caractères)")

    tenant_code = generate_tenant_code(data.nom_pharmacie)
    slug = generate_slug(data.nom_pharmacie)
    
    # Créer le tenant
    tenant = Tenant(
        tenant_code=tenant_code,
        slug=slug,
        nom_pharmacie=data.nom_pharmacie,
        nom_commercial=data.nom_pharmacie,
        ville=data.ville,
        pays=data.pays,
        telephone_principal=data.telephone,
        email_admin=data.email.lower(),
        nom_proprietaire=data.nom_complet,
        type_pharmacie=data.type_pharmacie,
        status="trial",
        max_users=3,
        max_products=100,
        current_plan="starter",
        max_pharmacies=1,
        trial_start_date=datetime.utcnow(),
        trial_end_date=datetime.utcnow() + timedelta(days=14),
    )
    db.add(tenant)
    db.flush()

    otp = generate_otp()

    # Créer l'utilisateur admin
    admin = User(
        tenant_id=tenant.id,
        nom_complet=data.nom_complet,
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        role="admin",
        actif=False,
        telephone=data.telephone,
        sms_code=otp,
        sms_expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRATION_MIN),
        login_attempts=0,
        sms_verify_attempts=0,
    )
    db.add(admin)
    
    # Créer la pharmacie principale
    pharmacy = Pharmacy(
        tenant_id=tenant.id,
        name=data.nom_pharmacie,
        address=data.ville,
        city=data.ville,
        phone=data.telephone,
        email=data.email.lower(),
        is_active=True,
        is_main=True,
        pharmacy_code=f"{tenant_code}001"
    )
    db.add(pharmacy)
    db.flush()

    # Associer l'admin à la pharmacie
    db.execute(
        UserPharmacy.insert().values(
            user_id=admin.id,
            pharmacy_id=pharmacy.id,
            is_primary=True,
            can_manage=True,
            role_in_pharmacy="admin"
        )
    )
    db.commit()

    try:
        formatted_phone = format_phone_for_twilio(data.telephone)
        logger.info(f"Envoi SMS à {formatted_phone} (original: {data.telephone})")
        send_sms(formatted_phone, f"Code de confirmation : {otp}")
        sms_sent = True
    except Exception as e:
        logger.error(f"Erreur envoi SMS: {e}")
        sms_sent = False

    return {
        "message": "Compte créé. Confirmation SMS requise.",
        "tenant_id": str(tenant.id),
        "user_id": str(admin.id),
        "tenant_code": tenant_code,
        "pharmacy_id": str(pharmacy.id),
        "verification_code": otp if not sms_sent else None,
        "sms_sent": sms_sent,
    }


@router.post("/verify-sms")
def verify_sms(data: VerifySMSSchema, db: Session = Depends(get_db)):
    """Vérification du code SMS et activation du compte"""
    email = data.email.lower()
    code = data.code.strip()
    
    if not email or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email et code requis")
    
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide (6 chiffres requis)")
    
    if not rate_limit_check(f"sms_verify_{email}", max_attempts=5, window_seconds=300):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de tentatives. Réessayez dans 5 minutes."
        )
    
    try:
        user = db.query(User).filter(
            User.email == email,
            User.actif == False
        ).first()
        
        if not user:
            logger.warning(f"Tentative vérification email inexistant/déjà activé: {email}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide ou expiré")
        
        if user.locked_until and user.locked_until > datetime.utcnow():
            remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
            raise HTTPException(
                status.HTTP_423_LOCKED,
                f"Compte bloqué. Réessayez dans {remaining} minutes."
            )
        
        if not user.sms_code or user.sms_code != code:
            user.sms_verify_attempts = getattr(user, 'sms_verify_attempts', 0) + 1
            
            if user.sms_verify_attempts >= 3:
                user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                logger.warning(f"Compte bloqué après 3 échecs SMS: {email}")
            
            db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide")
        
        if not user.sms_expires_at or user.sms_expires_at < datetime.utcnow():
            new_code = generate_otp()
            user.sms_code = new_code
            user.sms_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRATION_MIN)
            user.sms_verify_attempts = 0
            
            db.commit()
            
            try:
                formatted_phone = format_phone_for_twilio(user.telephone)
                send_sms(formatted_phone, f"Nouveau code: {new_code}")
            except Exception as sms_error:
                logger.error(f"Erreur envoi nouveau SMS: {sms_error}")
            
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Code expiré. Nouveau code envoyé."
            )
        
        if user.actif:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Compte déjà activé")
        
        # Activer le compte
        user.actif = True
        user.sms_code = None
        user.sms_expires_at = None
        user.sms_verify_attempts = 0
        user.locked_until = None
        user.activated_at = datetime.utcnow()
        
        # Activer le tenant
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
        if tenant:
            tenant.status = "active"
            tenant.activated_at = datetime.utcnow()
            if not tenant.trial_end_date:
                tenant.trial_end_date = datetime.utcnow() + timedelta(days=14)
        else:
            logger.error(f"Tenant non trouvé pour utilisateur: {user.id}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Erreur activation compte"
            )
        
        # Récupérer la pharmacie principale
        pharmacy = db.query(Pharmacy).filter(
            Pharmacy.tenant_id == tenant.id,
            Pharmacy.is_main == True
        ).first()
        
        logger.info(f"Compte activé: {email}, tenant: {tenant.tenant_code}")
        
        # Token d'accès
        token = create_access_token({
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "role": user.role,
            "email": user.email,
            "activated": True
        })
        
        db.commit()
        
        response_data = {
            "message": "Compte activé avec succès",
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "tenant_code": tenant.tenant_code,
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "nom_complet": user.nom_complet,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
                "activated": True
            },
            "tenant": {
                "id": str(tenant.id),
                "tenant_code": tenant.tenant_code,
                "nom_pharmacie": tenant.nom_pharmacie,
                "nom_commercial": tenant.nom_commercial,
                "ville": tenant.ville,
                "pays": tenant.pays,
                "email_admin": tenant.email_admin,
                "status": tenant.status,
                "current_plan": tenant.current_plan,
                "max_pharmacies": tenant.max_pharmacies
            }
        }
        
        if pharmacy:
            response_data["pharmacy"] = {
                "id": str(pharmacy.id),
                "name": pharmacy.name,
                "address": pharmacy.address,
                "city": pharmacy.city,
                "phone": pharmacy.phone,
                "email": pharmacy.email,
                "is_main": pharmacy.is_main,
                "pharmacy_code": pharmacy.pharmacy_code
            }
        
        return response_data
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur vérification SMS: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Erreur lors de la vérification. Réessayez."
        )


@router.post("/resend-sms")
def resend_sms_code(data: ResendSMSSchema, db: Session = Depends(get_db)):
    """Renvoie un nouveau code SMS de vérification"""
    email = data.email.lower()
    
    if not rate_limit_check(f"resend_sms_{email}", max_attempts=3, window_seconds=3600):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de demandes. Réessayez dans 1 heure."
        )
    
    try:
        user = db.query(User).filter(
            User.email == email,
            User.actif == False
        ).first()
        
        if not user:
            return {
                "message": "Si votre compte existe et n'est pas activé, un nouveau code sera envoyé."
            }
        
        if user.locked_until and user.locked_until > datetime.utcnow():
            remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
            raise HTTPException(
                status.HTTP_423_LOCKED,
                f"Compte bloqué. Réessayez dans {remaining} minutes."
            )
        
        new_code = generate_otp()
        user.sms_code = new_code
        user.sms_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRATION_MIN)
        user.sms_verify_attempts = 0
        
        db.commit()
        
        try:
            formatted_phone = format_phone_for_twilio(user.telephone)
            send_sms(formatted_phone, f"Nouveau code: {new_code}")
            sms_sent = True
        except Exception as e:
            logger.error(f"Erreur envoi SMS: {e}")
            sms_sent = False
        
        return {
            "message": "Nouveau code envoyé" if sms_sent else "Code généré mais SMS échoué",
            "sms_sent": sms_sent,
            "expires_in": OTP_EXPIRATION_MIN
        }
        
    except Exception as e:
        logger.error(f"Erreur renvoi SMS: {e}")
        db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Erreur lors de l'envoi du code"
        )


@router.post("/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    """Connexion utilisateur"""
    logger.info(f"Tentative de login pour: {data.email}")
    
    user = db.query(User).filter(User.email == data.email.lower()).first()
    
    if not user:
        logger.warning(f"Utilisateur non trouvé: {data.email}")
        raise HTTPException(401, "Identifiants invalides")
    
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
        raise HTTPException(403, f"Compte temporairement bloqué. Réessayez dans {remaining} minutes.")

    if not verify_password(data.password, user.password_hash):
        user.login_attempts += 1
        if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCK_MIN)
            user.login_attempts = 0
        db.commit()
        raise HTTPException(401, "Identifiants invalides")

    if not user.actif:
        raise HTTPException(403, "Compte non activé. Vérifiez votre SMS.")

    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant non trouvé")

    subscription_active = is_subscription_active(db, str(user.tenant_id))
    
    # Récupérer les pharmacies accessibles pour l'utilisateur
    accessible_pharmacies = db.query(Pharmacy).join(
        UserPharmacy, UserPharmacy.c.pharmacy_id == Pharmacy.id
    ).filter(
        UserPharmacy.c.user_id == user.id,
        Pharmacy.is_active == True
    ).all()
    
    # Récupérer la pharmacie principale
    main_pharmacy = next((p for p in accessible_pharmacies if p.is_main), None)
    if not main_pharmacy and accessible_pharmacies:
        main_pharmacy = accessible_pharmacies[0]
    
    # Récupérer les pharmacies actives du tenant
    pharmacies = db.query(Pharmacy).filter(
        Pharmacy.tenant_id == tenant.id,
        Pharmacy.is_active == True
    ).order_by(Pharmacy.is_main.desc(), Pharmacy.name).all()
    
    # Réinitialiser les tentatives de login
    user.login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    # Créer le token
    token = create_access_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
        "email": user.email,
        "subscription_active": subscription_active,
        "pharmacy_id": str(main_pharmacy.id) if main_pharmacy else None
    })

    # Préparer la réponse
    response_data = {
        "access_token": token,
        "token_type": "bearer",
        "subscription_active": subscription_active,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "nom_complet": user.nom_complet,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "actif": user.actif,
            "telephone": user.telephone
        },
        "tenant": {
            "id": str(tenant.id),
            "tenant_code": tenant.tenant_code,
            "nom_pharmacie": tenant.nom_pharmacie,
            "nom_commercial": tenant.nom_commercial,
            "ville": tenant.ville,
            "pays": tenant.pays,
            "email_admin": tenant.email_admin,
            "status": tenant.status,
            "current_plan": tenant.current_plan,
            "max_users": tenant.max_users,
            "max_products": tenant.max_products,
            "max_pharmacies": tenant.max_pharmacies,
            "trial_end_date": tenant.trial_end_date.isoformat() if tenant.trial_end_date else None
        },
        "pharmacies": []
    }
    
    # Ajouter les pharmacies
    for pharmacy in pharmacies:
        response_data["pharmacies"].append({
            "id": str(pharmacy.id),
            "name": pharmacy.name,
            "address": pharmacy.address,
            "city": pharmacy.city,
            "phone": pharmacy.phone,
            "email": pharmacy.email,
            "is_active": pharmacy.is_active,
            "is_main": pharmacy.is_main,
            "pharmacy_code": pharmacy.pharmacy_code,
            "created_at": pharmacy.created_at.isoformat() if pharmacy.created_at else None
        })
    
    # Ajouter la pharmacie active
    if main_pharmacy:
        response_data["current_pharmacy"] = {
            "id": str(main_pharmacy.id),
            "name": main_pharmacy.name,
            "address": main_pharmacy.address,
            "city": main_pharmacy.city,
            "phone": main_pharmacy.phone,
            "email": main_pharmacy.email,
            "is_main": main_pharmacy.is_main,
            "pharmacy_code": main_pharmacy.pharmacy_code
        }
    
    return response_data


# =========================
# ENDPOINTS RÉINITIALISATION MOT DE PASSE
# =========================
@router.post("/password/reset/request")
def request_reset(data: ResetRequestSchema, db: Session = Depends(get_db)):
    """Demande de réinitialisation de mot de passe"""
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user:
        return {"message": "Si le compte existe, un code sera envoyé"}

    code = generate_otp()
    user.reset_code = code
    user.reset_expires = datetime.utcnow() + timedelta(minutes=RESET_EXPIRATION_MIN)
    db.commit()

    try:
        formatted_phone = format_phone_for_twilio(user.telephone)
        send_sms(formatted_phone, f"Code réinitialisation: {code}")
        send_whatsapp(formatted_phone, f"Code réinitialisation: {code}")
        sms_sent = True
    except Exception as e:
        logger.error(f"Erreur envoi SMS/WhatsApp: {e}")
        sms_sent = False

    return {"message": "Code envoyé", "sms_sent": sms_sent}


@router.post("/password/reset/confirm")
def confirm_reset(data: ResetConfirmSchema, db: Session = Depends(get_db)):
    """Confirmation de réinitialisation de mot de passe"""
    user = db.query(User).filter(User.email == data.email.lower()).first()

    if not user or user.reset_code != data.code:
        raise HTTPException(400, "Code invalide")

    if user.reset_expires < datetime.utcnow():
        raise HTTPException(400, "Code expiré")

    if len(data.new_password.encode('utf-8')) > 72:
        raise HTTPException(400, "Mot de passe trop long (72 caractères max)")

    user.password_hash = hash_password(data.new_password)
    user.reset_code = None
    user.reset_expires = None
    user.login_attempts = 0
    user.locked_until = None
    db.commit()

    return {"message": "Mot de passe modifié"}


# =========================
# ENDPOINTS DE VÉRIFICATION
# =========================
@router.get("/activation-status/{email}")
def check_activation_status(email: EmailStr, db: Session = Depends(get_db)):
    """Vérifie le statut d'activation d'un compte"""
    user = db.query(User).filter(User.email == email.lower()).first()
    
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte non trouvé")
    
    response = {
        "email": user.email,
        "activated": user.actif,
        "locked": bool(user.locked_until and user.locked_until > datetime.utcnow()),
        "has_pending_code": bool(user.sms_code and user.sms_expires_at),
    }
    
    if response["has_pending_code"]:
        expires_in = max(0, int((user.sms_expires_at - datetime.utcnow()).total_seconds() / 60))
        response["code_expires_in_minutes"] = expires_in
    
    if response["locked"]:
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
        response["locked_until_minutes"] = remaining
    
    return response


# =========================
# ENDPOINTS INFORMATIONS TENANT/PHARMACIES
# =========================
@router.get("/pharmacy/limits/{tenant_id}")
def get_pharmacy_limits(tenant_id: str, db: Session = Depends(get_db)):
    """Récupère les limites de pharmacies pour un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant non trouvé")
    
    active_pharmacies_count = db.query(Pharmacy).filter(
        Pharmacy.tenant_id == tenant_id,
        Pharmacy.is_active == True
    ).count()
    
    return {
        "tenant_id": str(tenant.id),
        "current_plan": tenant.current_plan,
        "max_pharmacies": tenant.max_pharmacies,
        "active_pharmacies": active_pharmacies_count,
        "remaining_pharmacies": max(0, tenant.max_pharmacies - active_pharmacies_count),
        "can_create_more": active_pharmacies_count < tenant.max_pharmacies
    }


@router.get("/tenant-info/{tenant_id}")
def get_tenant_info(tenant_id: str, db: Session = Depends(get_db)):
    """Récupère les informations détaillées d'un tenant"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant non trouvé")
    
    return {
        "tenant": {
            "id": str(tenant.id),
            "tenant_code": tenant.tenant_code,
            "nom_pharmacie": tenant.nom_pharmacie,
            "nom_commercial": tenant.nom_commercial,
            "ville": tenant.ville,
            "pays": tenant.pays,
            "email_admin": tenant.email_admin,
            "status": tenant.status,
            "current_plan": tenant.current_plan,
            "max_pharmacies": tenant.max_pharmacies,
            "trial_end_date": tenant.trial_end_date.isoformat() if tenant.trial_end_date else None
        }
    }