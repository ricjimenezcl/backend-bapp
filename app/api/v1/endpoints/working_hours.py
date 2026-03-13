"""
Endpoints para gestión de horarios de trabajo del proveedor.

Rutas:
  GET  /working-hours/me               → Lista horarios propios (PROVIDER)
  POST /working-hours/me               → Crear/actualizar horario de un día (PROVIDER)
  GET  /working-hours/provider/{id}    → Ver horarios de un proveedor (público)
"""

import logging
from typing import List, Optional
from datetime import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.models.provider import Provider, ProviderWorkingHours

logger = logging.getLogger(__name__)

router = APIRouter()

DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class WorkingHoursCreate(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Lunes, 6=Domingo")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM")
    is_active: bool = True

    @model_validator(mode="after")
    def validate_times(self):
        start = time.fromisoformat(self.start_time)
        end = time.fromisoformat(self.end_time)
        if end <= start:
            raise ValueError("end_time debe ser posterior a start_time")
        return self


class WorkingHoursResponse(BaseModel):
    id: int
    provider_id: int
    day_of_week: int
    day_name: str
    start_time: str
    end_time: str
    is_active: bool

    model_config = {"from_attributes": True}


def _to_response(wh: ProviderWorkingHours) -> WorkingHoursResponse:
    return WorkingHoursResponse(
        id=wh.id,
        provider_id=wh.provider_id,
        day_of_week=wh.day_of_week,
        day_name=DAY_NAMES[wh.day_of_week],
        start_time=wh.start_time.strftime("%H:%M"),
        end_time=wh.end_time.strftime("%H:%M"),
        is_active=wh.is_active,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_provider_from_user(user: User, db: AsyncSession) -> Provider:
    """Resuelve el Provider del usuario autenticado."""
    if user.role != "PROVIDER":
        raise HTTPException(status_code=403, detail="Solo proveedores pueden gestionar sus horarios")
    result = await db.execute(select(Provider).where(Provider.user_id == user.id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Perfil de proveedor no encontrado")
    return provider


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/me", response_model=List[WorkingHoursResponse])
async def get_my_working_hours(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Lista los horarios de trabajo del proveedor autenticado."""
    provider = await _get_provider_from_user(current_user, db)

    result = await db.execute(
        select(ProviderWorkingHours)
        .where(ProviderWorkingHours.provider_id == provider.id)
        .order_by(ProviderWorkingHours.day_of_week)
    )
    hours = result.scalars().all()
    return [_to_response(h) for h in hours]


@router.post("/me", response_model=WorkingHoursResponse, status_code=status.HTTP_201_CREATED)
async def upsert_working_hours(
    hours_in: WorkingHoursCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Crea o actualiza el horario de un día de la semana para el proveedor.
    Si ya existe un registro para ese día, lo reemplaza (upsert).
    """
    provider = await _get_provider_from_user(current_user, db)

    # Buscar registro existente para ese día
    result = await db.execute(
        select(ProviderWorkingHours).where(
            ProviderWorkingHours.provider_id == provider.id,
            ProviderWorkingHours.day_of_week == hours_in.day_of_week,
        )
    )
    existing = result.scalar_one_or_none()

    start = time.fromisoformat(hours_in.start_time)
    end = time.fromisoformat(hours_in.end_time)

    if existing:
        existing.start_time = start
        existing.end_time = end
        existing.is_active = hours_in.is_active
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        logger.info(f"[HORARIOS] Proveedor {provider.id} actualizó horario día {hours_in.day_of_week}")
        return _to_response(existing)

    new_hours = ProviderWorkingHours(
        provider_id=provider.id,
        day_of_week=hours_in.day_of_week,
        start_time=start,
        end_time=end,
        is_active=hours_in.is_active,
    )
    db.add(new_hours)
    await db.commit()
    await db.refresh(new_hours)
    logger.info(f"[HORARIOS] Proveedor {provider.id} creó horario día {hours_in.day_of_week}")
    return _to_response(new_hours)


@router.delete("/me/{day_of_week}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_working_hours(
    day_of_week: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Elimina el horario de un día de la semana."""
    if day_of_week < 0 or day_of_week > 6:
        raise HTTPException(status_code=422, detail="day_of_week debe estar entre 0 y 6")

    provider = await _get_provider_from_user(current_user, db)

    result = await db.execute(
        select(ProviderWorkingHours).where(
            ProviderWorkingHours.provider_id == provider.id,
            ProviderWorkingHours.day_of_week == day_of_week,
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="No hay horario definido para ese día")

    await db.delete(existing)
    await db.commit()


@router.get("/provider/{provider_id}", response_model=List[WorkingHoursResponse])
async def get_provider_working_hours(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async),
):
    """Lista los horarios activos de un proveedor (endpoint público)."""
    result = await db.execute(
        select(ProviderWorkingHours).where(
            ProviderWorkingHours.provider_id == provider_id,
            ProviderWorkingHours.is_active == True,
        ).order_by(ProviderWorkingHours.day_of_week)
    )
    hours = result.scalars().all()
    return [_to_response(h) for h in hours]
