"""
Service Viewers Endpoints
Premium feature: proveedor paga $1.990 CLP para ver los clientes que visitaron sus servicios (7 días).
"""
import secrets
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, func as sqlfunc, distinct, text
from sqlalchemy.orm import joinedload
from pydantic import BaseModel

from app.core.database import get_db_async
from app.dependencies import get_current_user
from app.models.user import User, UserProfile
from app.models.provider import Provider, ServiceProvider
from app.models.service_view_unlock import ServiceViewUnlock
from app.models.service_view_event import ServiceViewEvent
from app.models.service_category import ServiceCategory

logger = logging.getLogger(__name__)

router = APIRouter()

UNLOCK_PRICE_CLP = Decimal("1990.00")
UNLOCK_DURATION_DAYS = 7

# ─────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────

class UnlockStatusResponse(BaseModel):
    is_unlocked: bool
    expires_at: Optional[datetime]
    days_remaining: Optional[int]
    hours_remaining: Optional[int]
    unlock_id: Optional[int]
    total_viewers: int = 0
    price_clp: int = 1990
    duration_days: int = 7


class UnlockInitResponse(BaseModel):
    payment_reference: str
    amount: float
    currency: str
    message: str
    checkout_url: Optional[str]


class ConfirmPaymentRequest(BaseModel):
    payment_reference: str


class ConfirmPaymentResponse(BaseModel):
    success: bool
    message: str
    expires_at: Optional[datetime]


class ServiceViewerClient(BaseModel):
    id: int
    display_name: str
    avatar_url: Optional[str]
    phone: Optional[str]
    service_viewed: str
    viewed_at: datetime
    is_masked: bool


class ServiceViewersResponse(BaseModel):
    is_unlocked: bool
    clients: List[ServiceViewerClient]
    total: int
    price_clp: int = 1990


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

async def _get_provider(current_user: User, db: AsyncSession) -> Provider:
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo proveedores pueden acceder.")
    result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Perfil de proveedor no encontrado.")
    return provider


async def _get_active_unlock(provider_id: int, db: AsyncSession) -> Optional[ServiceViewUnlock]:
    now = datetime.utcnow()
    result = await db.execute(
        select(ServiceViewUnlock).where(
            and_(
                ServiceViewUnlock.provider_id == provider_id,
                ServiceViewUnlock.status == "active",
                ServiceViewUnlock.expires_at > now,
            )
        )
    )
    return result.scalar_one_or_none()


async def _count_unique_viewers(provider_id: int, db: AsyncSession) -> int:
    """Cuenta visitantes únicos (user_id distinto) de los últimos 90 días."""
    cutoff = datetime.utcnow() - timedelta(days=90)
    result = await db.execute(
        select(sqlfunc.count(distinct(ServiceViewEvent.viewer_user_id))).where(
            and_(
                ServiceViewEvent.provider_id == provider_id,
                ServiceViewEvent.viewer_user_id.isnot(None),
                ServiceViewEvent.viewed_at >= cutoff,
            )
        )
    )
    return result.scalar() or 0


def _mask_name(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{'*' * (len(parts[0]) - 1)} {parts[1][0]}{'*' * (len(parts[1]) - 1)}"
    return f"{parts[0][0]}{'*' * (len(parts[0]) - 1)}"


async def _build_clients(
    provider_id: int,
    masked: bool,
    db: AsyncSession,
) -> List[ServiceViewerClient]:
    """
    Lee los últimos 90 días de ServiceViewEvent con user autenticado.
    Por cada usuario retorna su visita más reciente (DISTINCT ON viewer_user_id).
    """
    cutoff = datetime.utcnow() - timedelta(days=90)

    # Diagnóstico: cuántos eventos hay en total
    count_result = await db.execute(
        text("SELECT COUNT(*) FROM service_view_events WHERE provider_id = :pid AND viewer_user_id IS NOT NULL"),
        {"pid": provider_id}
    )
    total_events = count_result.scalar()
    logger.info(f"[service_viewers] provider_id={provider_id} → {total_events} eventos en BD")

    # DISTINCT ON: PostgreSQL retorna la fila más reciente por usuario
    raw = text("""
        SELECT DISTINCT ON (sve.viewer_user_id)
            sve.viewer_user_id,
            sve.service_provider_id,
            sve.viewed_at,
            u.email,
            up.full_name,
            up.avatar,
            up.phone,
            sc.name AS service_name
        FROM service_view_events sve
        JOIN users u ON u.id = sve.viewer_user_id
        LEFT JOIN user_profiles up ON up.user_id = sve.viewer_user_id
        LEFT JOIN service_providers sp ON sp.id = sve.service_provider_id
        LEFT JOIN service_categories sc ON sc.id = sp.service_id
        WHERE sve.provider_id = :provider_id
          AND sve.viewer_user_id IS NOT NULL
          AND sve.viewed_at >= :cutoff
        ORDER BY sve.viewer_user_id, sve.viewed_at DESC
    """)

    result = await db.execute(raw, {"provider_id": provider_id, "cutoff": cutoff})
    rows = result.all()
    logger.info(f"[service_viewers] provider_id={provider_id} → {len(rows)} visitantes únicos")

    clients: List[ServiceViewerClient] = []
    for r in rows:
        full_name = r.full_name or (r.email.split("@")[0] if r.email else "Usuario")
        if masked:
            clients.append(ServiceViewerClient(
                id=r.viewer_user_id,
                display_name=_mask_name(full_name),
                avatar_url=None,
                phone="***",
                service_viewed=r.service_name or "Servicio",
                viewed_at=r.viewed_at,
                is_masked=True,
            ))
        else:
            clients.append(ServiceViewerClient(
                id=r.viewer_user_id,
                display_name=full_name,
                avatar_url=r.avatar,
                phone=r.phone,
                service_viewed=r.service_name or "Servicio",
                viewed_at=r.viewed_at,
                is_masked=False,
            ))
    return clients


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@router.get("/service-viewers/status", response_model=UnlockStatusResponse)
async def get_service_viewers_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Verifica si el proveedor tiene acceso premium activo a la lista de clientes."""
    provider = await _get_provider(current_user, db)
    unlock = await _get_active_unlock(provider.id, db)
    total_viewers = await _count_unique_viewers(provider.id, db)

    if not unlock:
        return UnlockStatusResponse(
            is_unlocked=False,
            expires_at=None,
            days_remaining=None,
            hours_remaining=None,
            unlock_id=None,
            total_viewers=total_viewers,
        )

    now = datetime.utcnow()
    delta = unlock.expires_at - now
    total_seconds = max(0, int(delta.total_seconds()))
    days_rem = total_seconds // 86400
    hours_rem = (total_seconds % 86400) // 3600

    return UnlockStatusResponse(
        is_unlocked=True,
        expires_at=unlock.expires_at,
        days_remaining=days_rem,
        hours_remaining=hours_rem,
        unlock_id=unlock.id,
        total_viewers=total_viewers,
    )


@router.post("/service-viewers/unlock", response_model=UnlockInitResponse)
async def initiate_service_viewers_unlock(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Inicia el proceso de desbloqueo.
    Crea un registro 'pending' y retorna la referencia de pago.
    En producción, retorna la URL de MercadoPago/Webpay para redirigir al proveedor.
    """
    provider = await _get_provider(current_user, db)

    # Verificar si ya tiene unlock activo
    existing = await _get_active_unlock(provider.id, db)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya tienes acceso premium activo.",
        )

    # Generar referencia única
    payment_reference = f"SVU-{provider.id}-{secrets.token_hex(8).upper()}"

    unlock = ServiceViewUnlock(
        provider_id=provider.id,
        payment_reference=payment_reference,
        amount=UNLOCK_PRICE_CLP,
        currency="CLP",
        status="pending",
    )
    db.add(unlock)
    await db.commit()
    await db.refresh(unlock)

    # En producción: crear preferencia en MercadoPago y retornar init_point
    # checkout_url = await mercadopago_service.create_preference(...)
    checkout_url = None  # reemplazar con URL real del gateway

    return UnlockInitResponse(
        payment_reference=payment_reference,
        amount=float(UNLOCK_PRICE_CLP),
        currency="CLP",
        message="Pago iniciado. Confirma el pago para activar el acceso.",
        checkout_url=checkout_url,
    )


@router.post("/service-viewers/confirm-payment", response_model=ConfirmPaymentResponse)
async def confirm_service_viewers_payment(
    body: ConfirmPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Confirma el pago y activa el acceso premium por 7 días.
    En producción: validar el pago con el gateway antes de activar.
    """
    provider = await _get_provider(current_user, db)

    result = await db.execute(
        select(ServiceViewUnlock).where(
            and_(
                ServiceViewUnlock.payment_reference == body.payment_reference,
                ServiceViewUnlock.provider_id == provider.id,
            )
        )
    )
    unlock = result.scalar_one_or_none()
    if not unlock:
        raise HTTPException(status_code=404, detail="Referencia de pago no encontrada.")
    if unlock.status == "active":
        raise HTTPException(status_code=409, detail="Pago ya confirmado.")

    now = datetime.utcnow()
    unlock.status = "active"
    unlock.unlocked_at = now
    unlock.expires_at = now + timedelta(days=UNLOCK_DURATION_DAYS)
    await db.commit()
    await db.refresh(unlock)

    return ConfirmPaymentResponse(
        success=True,
        message=f"¡Acceso activado! Válido por {UNLOCK_DURATION_DAYS} días.",
        expires_at=unlock.expires_at,
    )


@router.get("/service-viewers/clients", response_model=ServiceViewersResponse)
async def get_service_viewers_clients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Retorna la lista de clientes que visitaron los servicios del proveedor (últimos 90 días).
    Si está bloqueado: datos enmascarados.
    Si está desbloqueado: datos completos.
    """
    provider = await _get_provider(current_user, db)
    unlock = await _get_active_unlock(provider.id, db)
    is_unlocked = unlock is not None

    clients = await _build_clients(provider.id, masked=not is_unlocked, db=db)

    return ServiceViewersResponse(
        is_unlocked=is_unlocked,
        clients=clients,
        total=len(clients),
    )
