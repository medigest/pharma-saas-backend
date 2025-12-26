from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog

def log_action(
    db: Session,
    tenant_id,
    user_id,
    action: str,
    cible: str,
    description: str,
    ip: str = None
):
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        cible=cible,
        description=description,
        ip_address=ip
    )
    db.add(log)
    db.commit()
