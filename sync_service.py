from sqlalchemy.orm import Session
from app.models.sync_log import SyncLog

def process_sync(db: Session, tenant_id, items):
    for item in items:
        log = SyncLog(
            tenant_id=tenant_id,
            table_name=item.table_name,
            action=item.action,
            data=item.data
        )
        db.add(log)

        # ⚠️ plus tard :
        # ici on appliquera CREATE / UPDATE / DELETE
        # sur les vraies tables (produits, ventes, etc.)

    db.commit()
