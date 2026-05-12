"""
ServiceViewEvent — registro por visita de un cliente a un servicio de proveedor.
Se inserta cada vez que un usuario autenticado llama a
  GET /providers/{provider_id}/services/{service_id}
"""
from sqlalchemy import Column, Integer, ForeignKey, TIMESTAMP, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ServiceViewEvent(Base):
    __tablename__ = "service_view_events"
    __table_args__ = (
        # Un mismo usuario no genera dos registros para el mismo servicio el mismo día
        # (deduplicación a nivel de BD, controlada también en el endpoint)
        Index("ix_sve_provider_viewer", "provider_id", "viewer_user_id"),
        Index("ix_sve_service_viewer",  "service_provider_id", "viewer_user_id"),
        {"extend_existing": True},
    )

    id                  = Column(Integer, primary_key=True, index=True)
    # Proveedor dueño del servicio visitado
    provider_id         = Column(Integer, ForeignKey("providers.id",  ondelete="CASCADE"), nullable=False, index=True)
    # Publicación de servicio específica que fue visitada
    service_provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    # Cliente que visitó (NULL = visita anónima / no autenticada)
    viewer_user_id      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    viewed_at           = Column(TIMESTAMP, server_default=func.now(), nullable=False, index=True)

    provider        = relationship("Provider",         foreign_keys=[provider_id],         lazy="select")
    service_provider = relationship("ServiceProvider", foreign_keys=[service_provider_id], lazy="select")
    viewer          = relationship("User",             foreign_keys=[viewer_user_id],       lazy="select")
