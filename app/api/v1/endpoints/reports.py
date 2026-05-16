"""
Reports Endpoints - Sistema de Reportes de Contenido Inapropiado
Permite a usuarios reportar contenido (perfiles, reseñas, servicios, mensajes)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.report import (
    ReportCreate, ReportReview, ReportResponse, ReportListResponse,
    ReportStatsResponse, ReportStatus
)
from app.services.report_service import ReportService

router = APIRouter()


@router.post("/", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    report_in: ReportCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Crear un reporte de contenido inapropiado.
    
    - El usuario actual será el reportante
    - Se valida que no haya reportes duplicados recientes (same entity, same reporter, last 24h)
    - Rate limiting: máximo 10 reportes por día por usuario
    """
    service = ReportService(db)
    return await service.create_report(current_user.id, report_in)


@router.get("/me", response_model=List[ReportResponse])
async def get_my_reports(
    status_filter: Optional[ReportStatus] = Query(None, description="Filtrar por estado"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener mis reportes enviados.
    
    - Solo muestra reportes donde current_user es el reportante
    """
    service = ReportService(db)
    return await service.get_user_reports(current_user.id, status_filter)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report_by_id(
    report_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener detalle de un reporte.
    
    - Usuario regular: solo puede ver sus propios reportes
    - Admin/Moderador: puede ver cualquier reporte
    """
    service = ReportService(db)
    report = await service.get_report_by_id(report_id)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Validar permisos
    is_admin = current_user.role == "ADMIN"
    is_reporter = report.reporter_id == current_user.id
    
    if not (is_admin or is_reporter):
        raise HTTPException(status_code=403, detail="Not authorized to view this report")
    
    return report


@router.get("/user/{user_id}", response_model=List[ReportResponse])
async def get_reports_about_user(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener reportes sobre un usuario específico (ADMIN ONLY).
    
    - Solo admins pueden ver reportes sobre otros usuarios
    - Útil para revisar historial de reportes de un usuario problemático
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ReportService(db)
    return await service.get_reports_about_user(user_id)


@router.put("/{report_id}/review", response_model=ReportResponse)
async def review_report(
    report_id: int,
    review_data: ReportReview,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Revisar un reporte y tomar acción (ADMIN/MODERATOR ONLY).
    
    - Cambia el estado del reporte
    - Registra la acción tomada
    - Puede suspender/banear al usuario reportado según la acción
    """
    if current_user.role not in ["ADMIN", "MODERATOR"]:
        raise HTTPException(status_code=403, detail="Moderator access required")
    
    service = ReportService(db)
    return await service.review_report(report_id, current_user.id, review_data)


@router.get("/stats", response_model=ReportStatsResponse)
async def get_report_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener estadísticas de reportes (ADMIN ONLY).
    
    - Total de reportes por estado
    - Reportes por tipo
    - Reportes en los últimos 30 días
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ReportService(db)
    return await service.get_report_stats()


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_report(
    report_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Cancelar un reporte (solo si es el reportante y está PENDING).
    
    - Solo el usuario que hizo el reporte puede cancelarlo
    - Solo si está en estado PENDING
    """
    service = ReportService(db)
    success = await service.cancel_report(report_id, current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Cannot cancel report (not found, not yours, or already reviewed)"
        )
    
    return None
