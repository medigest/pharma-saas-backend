# app/models/user_pharmacy.py - Version avec classe déclarative
from sqlalchemy import (
    Column, 
    ForeignKey, 
    Integer, 
    Boolean, 
    String, 
    DateTime,
    UniqueConstraint,
    Index
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base

class UserPharmacy(Base):
    """Modèle pour la relation Many-to-Many entre utilisateurs et pharmacies"""
    __tablename__ = 'user_pharmacy'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey('pharmacies.id', ondelete='CASCADE'), nullable=False)
    is_primary = Column(Boolean, default=False, comment='Pharmacie principale pour cet utilisateur')
    can_manage = Column(Boolean, default=False, comment='Peut gérer cette pharmacie')
    role_in_pharmacy = Column(String(50), default='employee', comment='Rôle dans cette pharmacie spécifique')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    user = relationship(
        "User",
        back_populates="pharmacy_associations",
        overlaps="pharmacies,users"
    )

    pharmacy = relationship(
        "Pharmacy",
        back_populates="user_associations",
        overlaps="pharmacies,users"
    )
    
    # Index et contraintes
    __table_args__ = (
        Index('idx_user_pharmacy_user', 'user_id'),
        Index('idx_user_pharmacy_pharmacy', 'pharmacy_id'),
        Index('idx_user_pharmacy_primary', 'user_id', 'is_primary'),
        UniqueConstraint('user_id', 'pharmacy_id', name='uq_user_pharmacy'),
    )