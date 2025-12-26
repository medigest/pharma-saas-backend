# app/models/audit_log.py
import uuid
import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Index, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AuditLog(Base):
    """
    Modèle pour les logs d'audit avec fonctionnalités avancées
    """
    __tablename__ = "audit_logs"

    # =======================
    # Colonnes principales
    # =======================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # =======================
    # Informations sur l'action
    # =======================
    action_type = Column(
        String(50), 
        nullable=False, 
        index=True,
        comment="CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT, IMPORT, VALIDATE, CANCEL"
    )
    
    action_category = Column(
        String(50),
        nullable=False,
        index=True,
        comment="system, security, data, financial, inventory, sales, purchases, clients, users"
    )
    
    entity_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="product, sale, purchase, client, user, inventory, stock_movement, payment, refund"
    )
    
    entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    entity_name = Column(String(200), nullable=True)
    
    # =======================
    # Détails de l'action
    # =======================
    description = Column(Text, nullable=True)
    details = Column(JSON, nullable=True, comment="Données détaillées au format JSON")
    
    changes_before = Column(JSON, nullable=True, comment="État avant modification")
    changes_after = Column(JSON, nullable=True, comment="État après modification")
    changes_summary = Column(Text, nullable=True, comment="Résumé des changements")
    
    # =======================
    # Contexte de sécurité
    # =======================
    ip_address = Column(String(45), nullable=True, index=True, comment="IPv4 ou IPv6")
    user_agent = Column(String(500), nullable=True)
    device_type = Column(String(50), nullable=True, comment="mobile, tablet, desktop, unknown")
    browser = Column(String(100), nullable=True)
    operating_system = Column(String(100), nullable=True)
    
    # =======================
    # Géolocalisation
    # =======================
    country = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    latitude = Column(String(20), nullable=True)
    longitude = Column(String(20), nullable=True)
    
    # =======================
    # Performance et métriques
    # =======================
    duration_ms = Column(Integer, nullable=True, comment="Durée de l'action en millisecondes")
    status_code = Column(Integer, nullable=True, comment="Code HTTP ou statut métier")
    error_message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)
    
    # =======================
    # Références
    # =======================
    reference_number = Column(String(100), nullable=True, index=True, comment="Numéro de référence (vente, achat, etc.)")
    batch_id = Column(UUID(as_uuid=True), nullable=True, index=True, comment="ID de lot pour les opérations groupées")
    parent_log_id = Column(UUID(as_uuid=True), ForeignKey("audit_logs.id", ondelete="SET NULL"), nullable=True)
    
    # =======================
    # Métadonnées
    # =======================
    severity = Column(
        String(20), 
        nullable=False, 
        default="info",
        index=True,
        comment="debug, info, warning, error, critical"
    )
    
    source_module = Column(String(100), nullable=True, comment="Module source (api, service, worker, etc.)")
    request_id = Column(String(100), nullable=True, index=True, comment="ID de requête pour le tracing")
    session_id = Column(String(100), nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # =======================
    # Relations
    # =======================
    tenant = relationship("Tenant")
    user = relationship("User", foreign_keys=[user_id])
    parent_log = relationship("AuditLog", remote_side=[id], backref="child_logs")
    
    # =======================
    # Indexes pour optimisation
    # =======================
    __table_args__ = (
        # Index composites pour les requêtes fréquentes
        Index("ix_audit_logs_tenant_entity", "tenant_id", "entity_type", "created_at"),
        Index("ix_audit_logs_tenant_user_date", "tenant_id", "user_id", "created_at"),
        Index("ix_audit_logs_tenant_action_date", "tenant_id", "action_type", "created_at"),
        Index("ix_audit_logs_tenant_severity", "tenant_id", "severity", "created_at"),
        Index("ix_audit_logs_tenant_ip", "tenant_id", "ip_address", "created_at"),
        
        # Index pour les recherches par référence
        Index("ix_audit_logs_reference", "reference_number"),
        Index("ix_audit_logs_batch", "batch_id"),
        
        # Index pour les analyses temporelles
        Index("ix_audit_logs_date_hour", "created_at"),
        Index("ix_audit_logs_tenant_date_range", "tenant_id", "created_at"),
    )
    
    # =======================
    # Méthodes utilitaires
    # =======================
    @classmethod
    def create_log(
        cls,
        db,
        tenant_id: UUID,
        user_id: Optional[UUID],
        action_type: str,
        action_category: str,
        entity_type: str,
        entity_id: Optional[UUID] = None,
        entity_name: Optional[str] = None,
        description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        changes_before: Optional[Dict[str, Any]] = None,
        changes_after: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        reference_number: Optional[str] = None,
        severity: str = "info",
        **kwargs
    ):
        """
        Méthode utilitaire pour créer un log d'audit
        """
        # Analyser user_agent pour extraire des informations
        device_info = cls._parse_user_agent(user_agent)
        
        # Créer le résumé des changements
        changes_summary = cls._generate_changes_summary(changes_before, changes_after)
        
        log = cls(
            tenant_id=tenant_id,
            user_id=user_id,
            action_type=action_type,
            action_category=action_category,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            description=description,
            details=details or {},
            changes_before=changes_before or {},
            changes_after=changes_after or {},
            changes_summary=changes_summary,
            ip_address=ip_address,
            user_agent=user_agent,
            device_type=device_info.get("device_type"),
            browser=device_info.get("browser"),
            operating_system=device_info.get("os"),
            reference_number=reference_number,
            severity=severity,
            source_module=kwargs.get("source_module"),
            request_id=kwargs.get("request_id"),
            session_id=kwargs.get("session_id"),
            duration_ms=kwargs.get("duration_ms"),
            status_code=kwargs.get("status_code"),
            error_message=kwargs.get("error_message"),
            stack_trace=kwargs.get("stack_trace"),
            batch_id=kwargs.get("batch_id"),
            parent_log_id=kwargs.get("parent_log_id"),
            country=kwargs.get("country"),
            region=kwargs.get("region"),
            city=kwargs.get("city"),
            latitude=kwargs.get("latitude"),
            longitude=kwargs.get("longitude"),
        )
        
        db.add(log)
        return log
    
    @staticmethod
    def _parse_user_agent(user_agent: Optional[str]) -> Dict[str, str]:
        """
        Analyse le User-Agent pour extraire des informations
        """
        if not user_agent:
            return {"device_type": "unknown", "browser": "unknown", "os": "unknown"}
        
        result = {
            "device_type": "desktop",
            "browser": "unknown",
            "os": "unknown"
        }
        
        user_agent = user_agent.lower()
        
        # Détection du type d'appareil
        if "mobile" in user_agent:
            result["device_type"] = "mobile"
        elif "tablet" in user_agent or "ipad" in user_agent:
            result["device_type"] = "tablet"
        
        # Détection du navigateur
        if "chrome" in user_agent and "chromium" not in user_agent:
            result["browser"] = "chrome"
        elif "firefox" in user_agent:
            result["browser"] = "firefox"
        elif "safari" in user_agent and "chrome" not in user_agent:
            result["browser"] = "safari"
        elif "edge" in user_agent:
            result["browser"] = "edge"
        elif "opera" in user_agent:
            result["browser"] = "opera"
        
        # Détection du système d'exploitation
        if "windows" in user_agent:
            result["os"] = "windows"
        elif "mac os" in user_agent or "macos" in user_agent:
            result["os"] = "macos"
        elif "linux" in user_agent:
            result["os"] = "linux"
        elif "android" in user_agent:
            result["os"] = "android"
        elif "ios" in user_agent or "iphone" in user_agent or "ipad" in user_agent:
            result["os"] = "ios"
        
        return result
    
    @staticmethod
    def _generate_changes_summary(before: Optional[Dict], after: Optional[Dict]) -> Optional[str]:
        """
        Génère un résumé lisible des changements
        """
        if not before or not after:
            return None
        
        changes = []
        
        for key in set(before.keys()) | set(after.keys()):
            old_value = before.get(key)
            new_value = after.get(key)
            
            if old_value != new_value:
                if isinstance(old_value, dict) and isinstance(new_value, dict):
                    # Pour les objets complexes, juste mentionner qu'il y a eu changement
                    changes.append(f"{key}: [object modifié]")
                else:
                    # Tronquer les valeurs longues
                    old_str = str(old_value)[:50] + ("..." if len(str(old_value)) > 50 else "")
                    new_str = str(new_value)[:50] + ("..." if len(str(new_value)) > 50 else "")
                    changes.append(f"{key}: {old_str} → {new_str}")
        
        if not changes:
            return "Aucun changement détecté"
        
        return "; ".join(changes[:10]) + (f"... (+{len(changes)-10} autres)" if len(changes) > 10 else "")
    
    # =======================
    # Propriétés calculées
    # =======================
    @property
    def is_successful(self) -> bool:
        """Vérifie si l'action a réussi"""
        return self.severity not in ["error", "critical"]
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Durée en secondes"""
        if self.duration_ms:
            return self.duration_ms / 1000.0
        return None
    
    @property
    def location_info(self) -> Optional[str]:
        """Informations de localisation formatées"""
        if self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return None
    
    @property
    def device_info(self) -> str:
        """Informations sur l'appareil formatées"""
        parts = []
        if self.device_type:
            parts.append(self.device_type)
        if self.browser:
            parts.append(self.browser)
        if self.operating_system:
            parts.append(self.operating_system)
        return " / ".join(parts) if parts else "Inconnu"
    
    # =======================
    # Méthodes de sérialisation
    # =======================
    def to_dict(self, include_details: bool = True) -> Dict[str, Any]:
        """
        Convertit le log en dictionnaire
        
        Args:
            include_details: Inclure les détails JSON (peut être volumineux)
        """
        data = {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "user_name": self.user.nom_complet if self.user else None,
            "action_type": self.action_type,
            "action_category": self.action_category,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "entity_name": self.entity_name,
            "description": self.description,
            "changes_summary": self.changes_summary,
            "ip_address": self.ip_address,
            "device_info": self.device_info,
            "location_info": self.location_info,
            "reference_number": self.reference_number,
            "severity": self.severity,
            "source_module": self.source_module,
            "duration_ms": self.duration_ms,
            "duration_seconds": self.duration_seconds,
            "status_code": self.status_code,
            "is_successful": self.is_successful,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_details:
            data.update({
                "details": self.details,
                "changes_before": self.changes_before,
                "changes_after": self.changes_after,
                "user_agent": self.user_agent,
                "country": self.country,
                "region": self.region,
                "city": self.city,
                "latitude": self.latitude,
                "longitude": self.longitude,
                "error_message": self.error_message,
                "stack_trace": self.stack_trace,
                "request_id": self.request_id,
                "session_id": self.session_id,
                "batch_id": str(self.batch_id) if self.batch_id else None,
                "parent_log_id": str(self.parent_log_id) if self.parent_log_id else None,
            })
        
        return data
    
    def to_json(self, include_details: bool = True) -> str:
        """Convertit en JSON"""
        return json.dumps(self.to_dict(include_details), ensure_ascii=False, indent=2)
    
    # =======================
    # Méthodes de recherche
    # =======================
    @classmethod
    def search_logs(
        cls,
        db,
        tenant_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[UUID] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        action_type: Optional[str] = None,
        severity: Optional[str] = None,
        ip_address: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ):
        """Recherche avancée dans les logs"""
        query = db.query(cls).filter(cls.tenant_id == tenant_id)
        
        # Filtres optionnels
        if start_date:
            query = query.filter(cls.created_at >= start_date)
        if end_date:
            query = query.filter(cls.created_at <= end_date)
        if user_id:
            query = query.filter(cls.user_id == user_id)
        if entity_type:
            query = query.filter(cls.entity_type == entity_type)
        if entity_id:
            query = query.filter(cls.entity_id == entity_id)
        if action_type:
            query = query.filter(cls.action_type == action_type)
        if severity:
            query = query.filter(cls.severity == severity)
        if ip_address:
            query = query.filter(cls.ip_address == ip_address)
        
        # Trier par date décroissante
        query = query.order_by(cls.created_at.desc())
        
        # Pagination
        total = query.count()
        logs = query.offset(offset).limit(limit).all()
        
        return {
            "logs": [log.to_dict(include_details=False) for log in logs],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total
        }
    
    # =======================
    # Méthodes de statistiques
    # =======================
    @classmethod
    def get_statistics(
        cls,
        db,
        tenant_id: UUID,
        period_days: int = 30
    ) -> Dict[str, Any]:
        """Récupère des statistiques sur les logs"""
        from datetime import datetime, timedelta
        from sqlalchemy import func, and_
        
        start_date = datetime.utcnow() - timedelta(days=period_days)
        
        # Actions par type
        actions_by_type = db.query(
            cls.action_type,
            func.count(cls.id).label("count")
        ).filter(
            cls.tenant_id == tenant_id,
            cls.created_at >= start_date
        ).group_by(cls.action_type).all()
        
        # Actions par catégorie
        actions_by_category = db.query(
            cls.action_category,
            func.count(cls.id).label("count")
        ).filter(
            cls.tenant_id == tenant_id,
            cls.created_at >= start_date
        ).group_by(cls.action_category).all()
        
        # Actions par entité
        actions_by_entity = db.query(
            cls.entity_type,
            func.count(cls.id).label("count")
        ).filter(
            cls.tenant_id == tenant_id,
            cls.created_at >= start_date
        ).group_by(cls.entity_type).all()
        
        # Séverités
        severities = db.query(
            cls.severity,
            func.count(cls.id).label("count")
        ).filter(
            cls.tenant_id == tenant_id,
            cls.created_at >= start_date
        ).group_by(cls.severity).all()
        
        # Top utilisateurs
        top_users = db.query(
            cls.user_id,
            func.count(cls.id).label("count")
        ).filter(
            cls.tenant_id == tenant_id,
            cls.created_at >= start_date,
            cls.user_id.isnot(None)
        ).group_by(cls.user_id).order_by(func.count(cls.id).desc()).limit(10).all()
        
        # Dernières erreurs
        recent_errors = db.query(cls).filter(
            cls.tenant_id == tenant_id,
            cls.severity.in_(["error", "critical"]),
            cls.created_at >= start_date
        ).order_by(cls.created_at.desc()).limit(10).all()
        
        return {
            "period_days": period_days,
            "start_date": start_date.isoformat(),
            "total_actions": sum(count for _, count in actions_by_type),
            "actions_by_type": dict(actions_by_type),
            "actions_by_category": dict(actions_by_category),
            "actions_by_entity": dict(actions_by_entity),
            "severities": dict(severities),
            "top_users": [
                {"user_id": str(user_id), "count": count}
                for user_id, count in top_users
            ],
            "recent_errors": [log.to_dict() for log in recent_errors]
        }
    
    def __repr__(self) -> str:
        return f"<AuditLog {self.action_type} {self.entity_type} {self.entity_id} by {self.user_id}>"