"""
Report Service - Lógica de negocio para sistema de reportes
"""
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.models.report import Report, ReportType, ReportStatus, ReportedEntityType, ModerationAction
from app.models.user import User
from app.models.moderation_history import ModerationHistory, ModerationType
from app.schemas.report import ReportCreate, ReportReview, ReportResponse, ReportStatsResponse
from fastapi import HTTPException, status


class ReportService:
    """Servicio para gestión de reportes"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_report(self, reporter_id: int, report_data: ReportCreate) -> ReportResponse:
        """
        Crear un nuevo reporte
        
        Validaciones:
        - No duplicar reportes (misma entidad, mismo reportante, últimas 24h)
        - Rate limiting: máximo 10 reportes por día
        """
        # Validar duplicados (24 horas)
        yesterday = datetime.utcnow() - timedelta(hours=24)
        existing_stmt = select(Report).where(
            and_(
                Report.reporter_id == reporter_id,
                Report.reported_entity_type == report_data.reported_entity_type,
                Report.reported_entity_id == report_data.reported_entity_id,
                Report.created_at >= yesterday
            )
        )
        existing_result = await self.db.execute(existing_stmt)
        existing_report = existing_result.scalar_one_or_none()
        
        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already reported this content recently"
            )
        
        # Rate limiting (10 reportes por día)
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        count_stmt = select(func.count(Report.id)).where(
            and_(
                Report.reporter_id == reporter_id,
                Report.created_at >= today_start
            )
        )
        count_result = await self.db.execute(count_stmt)
        reports_today = count_result.scalar()
        
        if reports_today >= 10:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily report limit reached. Please try again tomorrow."
            )
        
        # Crear reporte
        report = Report(
            report_type=report_data.report_type,
            reported_entity_type=report_data.reported_entity_type,
            reported_entity_id=report_data.reported_entity_id,
            reporter_id=reporter_id,
            reported_user_id=report_data.reported_user_id,
            description=report_data.description,
            evidence_urls=report_data.evidence_urls,
            status=ReportStatus.PENDING
        )
        
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        
        return ReportResponse.model_validate(report)
    
    async def get_user_reports(
        self, 
        user_id: int, 
        status_filter: Optional[ReportStatus] = None
    ) -> List[ReportResponse]:
        """Obtener reportes enviados por un usuario"""
        stmt = select(Report).where(Report.reporter_id == user_id)
        
        if status_filter:
            stmt = stmt.where(Report.status == status_filter)
        
        stmt = stmt.order_by(Report.created_at.desc())
        
        result = await self.db.execute(stmt)
        reports = result.scalars().all()
        
        return [ReportResponse.model_validate(r) for r in reports]
    
    async def get_report_by_id(self, report_id: int) -> Optional[ReportResponse]:
        """Obtener un reporte por ID"""
        stmt = select(Report).where(Report.id == report_id)
        result = await self.db.execute(stmt)
        report = result.scalar_one_or_none()
        
        if not report:
            return None
        
        return ReportResponse.model_validate(report)
    
    async def get_reports_about_user(self, user_id: int) -> List[ReportResponse]:
        """Obtener reportes sobre un usuario (admin only)"""
        stmt = select(Report).where(
            Report.reported_user_id == user_id
        ).order_by(Report.created_at.desc())
        
        result = await self.db.execute(stmt)
        reports = result.scalars().all()
        
        return [ReportResponse.model_validate(r) for r in reports]
    
    async def review_report(
        self, 
        report_id: int, 
        reviewer_id: int, 
        review_data: ReportReview
    ) -> ReportResponse:
        """
        Revisar un reporte y tomar acción (moderador/admin)
        
        Si la acción es TEMPORARY_SUSPENSION o PERMANENT_BAN, actualiza el estado del usuario
        """
        stmt = select(Report).where(Report.id == report_id)
        result = await self.db.execute(stmt)
        report = result.scalar_one_or_none()
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Actualizar reporte
        report.status = review_data.status
        report.reviewed_by = reviewer_id
        report.reviewed_at = datetime.utcnow()
        report.review_notes = review_data.review_notes
        report.action_taken = review_data.action_taken
        report.action_details = review_data.action_details
        
        # Aplicar acción de moderación si corresponde
        if review_data.action_taken and report.reported_user_id:
            await self._apply_moderation_action(
                report.reported_user_id,
                reviewer_id,
                review_data.action_taken,
                report.id,
                review_data.action_details or "Moderation action from report"
            )
        
        await self.db.commit()
        await self.db.refresh(report)
        
        return ReportResponse.model_validate(report)
    
    async def _apply_moderation_action(
        self,
        user_id: int,
        moderator_id: int,
        action: ModerationAction,
        report_id: int,
        reason: str
    ):
        """Aplicar acción de moderación al usuario"""
        # Obtener usuario
        user_stmt = select(User).where(User.id == user_id)
        user_result = await self.db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        
        if not user:
            return
        
        # Actualizar estado del usuario según acción
        if action == ModerationAction.TEMPORARY_SUSPENSION:
            user.status = "SUSPENDED"
            mod_type = ModerationType.USER_SUSPENDED
            
        elif action == ModerationAction.PERMANENT_BAN:
            user.status = "REJECTED"
            mod_type = ModerationType.USER_BANNED
            
        elif action == ModerationAction.WARNING:
            mod_type = ModerationType.USER_WARNING
            
        else:
            return  # No modificar usuario para otras acciones
        
        # Registrar en historial de moderación
        history = ModerationHistory(
            moderation_type=mod_type,
            user_id=user_id,
            moderator_id=moderator_id,
            report_id=report_id,
            reason=reason
        )
        self.db.add(history)
    
    async def cancel_report(self, report_id: int, user_id: int) -> bool:
        """
        Cancelar un reporte (solo si es el reportante y está PENDING)
        """
        stmt = select(Report).where(
            and_(
                Report.id == report_id,
                Report.reporter_id == user_id,
                Report.status == ReportStatus.PENDING
            )
        )
        result = await self.db.execute(stmt)
        report = result.scalar_one_or_none()
        
        if not report:
            return False
        
        await self.db.delete(report)
        await self.db.commit()
        return True
    
    async def get_report_stats(self) -> ReportStatsResponse:
        """Obtener estadísticas de reportes (admin only)"""
        # Total de reportes
        total_stmt = select(func.count(Report.id))
        total_result = await self.db.execute(total_stmt)
        total_reports = total_result.scalar()
        
        # Por estado
        pending_stmt = select(func.count(Report.id)).where(Report.status == ReportStatus.PENDING)
        pending_result = await self.db.execute(pending_stmt)
        pending_reports = pending_result.scalar()
        
        resolved_stmt = select(func.count(Report.id)).where(Report.status == ReportStatus.RESOLVED)
        resolved_result = await self.db.execute(resolved_stmt)
        resolved_reports = resolved_result.scalar()
        
        dismissed_stmt = select(func.count(Report.id)).where(Report.status == ReportStatus.DISMISSED)
        dismissed_result = await self.db.execute(dismissed_stmt)
        dismissed_reports = dismissed_result.scalar()
        
        escalated_stmt = select(func.count(Report.id)).where(Report.status == ReportStatus.ESCALATED)
        escalated_result = await self.db.execute(escalated_stmt)
        escalated_reports = escalated_result.scalar()
        
        # Últimos 30 días
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_stmt = select(func.count(Report.id)).where(Report.created_at >= thirty_days_ago)
        recent_result = await self.db.execute(recent_stmt)
        reports_last_30_days = recent_result.scalar()
        
        # Por tipo (simplified)
        reports_by_type = {}
        for report_type in ReportType:
            type_stmt = select(func.count(Report.id)).where(Report.report_type == report_type)
            type_result = await self.db.execute(type_stmt)
            reports_by_type[report_type.value] = type_result.scalar()
        
        return ReportStatsResponse(
            total_reports=total_reports,
            pending_reports=pending_reports,
            resolved_reports=resolved_reports,
            dismissed_reports=dismissed_reports,
            escalated_reports=escalated_reports,
            reports_by_type=reports_by_type,
            reports_last_30_days=reports_last_30_days
        )
