import logging
from typing import Any, Optional, Annotated, Literal
import json

from app.dependencies import get_current_active_user

from fastapi import Body, APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import jwt as pyjwt
import aiohttp
import secrets
from datetime import datetime, timedelta, timezone
from app.models.user import User
from sqlalchemy import func
from sqlalchemy.future import select
from app.core.database import get_db_async
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import UserResponse, ClientRegister, Token
from app.schemas.provider import ProviderRegister, ProviderResponse
from pydantic import BaseModel, EmailStr, ValidationError
from app.services.auth_service import AuthService
from app.services.email_service import email_service
from app.core.config import settings
from app.core.redis import rate_limit, cache_set, cache_get

logger = logging.getLogger(__name__)
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

router = APIRouter()

class LoginRequest(BaseModel):
    """Schema para el login"""
    username: str
    password: str
    role: Optional[str] = None


class SetNewPasswordRequest(BaseModel):
    token: str
    new_password: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


def _normalize_registration_source(value: Optional[str]) -> Literal["web", "mobile"]:
    normalized = (value or "").strip().lower()
    return "mobile" if normalized == "mobile" else "web"


def _cookie_secure() -> bool:
    if settings.COOKIE_SECURE is not None:
        return settings.COOKIE_SECURE
    return (settings.ENVIRONMENT or "").lower() == "production"


def _cookie_samesite() -> str:
    raw = (settings.COOKIE_SAMESITE or ("none" if _cookie_secure() else "lax")).lower()
    if raw not in {"lax", "strict", "none"}:
        return "none" if _cookie_secure() else "lax"
    return raw


def _set_auth_cookies(response: Response, access_token: str, refresh_token: Optional[str] = None) -> None:
    access_max_age = int((settings.ACCESS_TOKEN_EXPIRE_MINUTES or 30) * 60)
    refresh_max_age = int((settings.REFRESH_TOKEN_EXPIRE_DAYS or 30) * 24 * 60 * 60)
    secure = _cookie_secure()
    same_site = _cookie_samesite()

    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=access_max_age,
        httponly=True,
        secure=secure,
        samesite=same_site,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )
    if refresh_token:
        response.set_cookie(
            key=settings.REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=refresh_max_age,
            httponly=True,
            secure=secure,
            samesite=same_site,
            domain=settings.COOKIE_DOMAIN,
            path="/",
        )


def _clear_auth_cookies(response: Response) -> None:
    secure = _cookie_secure()
    same_site = _cookie_samesite()
    response.delete_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        secure=secure,
        httponly=True,
        samesite=same_site,
    )
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        secure=secure,
        httponly=True,
        samesite=same_site,
    )


@router.get("/login-roles")
async def get_login_roles(email: EmailStr, db: Annotated[AsyncSession, Depends(get_db_async)]):
    """Retorna los roles disponibles para un correo (p.ej. CLIENT y PROVIDER)."""
    normalized_email = (email or "").strip().lower()
    result = await db.execute(
        select(User.role).where(func.lower(func.trim(User.email)) == normalized_email)
    )
    roles = sorted({row[0] for row in result.all() if row and row[0]})
    return {
        "email": normalized_email,
        "roles": roles,
        "multiple_roles": len(roles) > 1,
    }

# Endpoint para solicitar recuperación de contraseña
@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    body: Optional[LogoutRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_db_async),
):
    """Invalida el token actual añadiéndolo a la blacklist de Redis."""
    token_candidate = None
    if credentials and credentials.credentials:
        token_candidate = credentials.credentials
    if not token_candidate:
        token_candidate = request.cookies.get(settings.ACCESS_COOKIE_NAME)

    if not token_candidate:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        payload = jwt.decode(
            token_candidate,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

    if payload.get("token_type", "access") != "access":
        raise HTTPException(status_code=401, detail="Tipo de token inválido")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")

    result = await db.execute(select(User).where(User.email == email))
    current_user = result.scalar_one_or_none()
    if not current_user or current_user.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Usuario inválido o inactivo")

    try:
        payload = jwt.decode(
            token_candidate,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            remaining_ttl = max(int(exp - datetime.now(timezone.utc).timestamp()), 1)
            cache_set(f"blacklist:jwt:{jti}", "1", ttl=remaining_ttl)
            logger.info(f"Token blacklisted for user {current_user.id} (jti={jti}, ttl={remaining_ttl}s)")
    except JWTError:
        pass  # Token ya expirado — no hay nada que blacklistear
    except Exception as e:
        logger.warning(f"Logout blacklist error (non-critical): {e}")

    # Revocar refresh token enviado por cliente (opcional)
    try:
        refresh_token = body.refresh_token if body else None
        if not refresh_token and request is not None:
            refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
        if refresh_token:
            refresh_payload = jwt.decode(
                refresh_token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
            if refresh_payload.get("token_type") == "refresh":
                r_jti = refresh_payload.get("jti")
                r_exp = refresh_payload.get("exp")
                if r_jti and r_exp:
                    r_ttl = max(int(r_exp - datetime.now(timezone.utc).timestamp()), 1)
                    cache_set(f"blacklist:refresh:{r_jti}", "1", ttl=r_ttl)
    except JWTError:
        pass
    except Exception as e:
        logger.warning(f"Logout refresh blacklist error (non-critical): {e}")

    if response is not None:
        _clear_auth_cookies(response)
    return {"message": "Sesión cerrada correctamente"}


@router.post("/reset-password")
async def reset_password(
    request: Request,
    email: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db_async)
):
    email_normalized = (email or "").strip().lower()
    if not email_normalized:
        raise HTTPException(
            status_code=400,
            detail="Debes ingresar un correo electrónico."
        )
    if "@" not in email_normalized or "." not in email_normalized.split("@")[-1]:
        raise HTTPException(
            status_code=400,
            detail="Debes ingresar un correo electrónico válido."
        )

    # Rate limit: 3 solicitudes por email por hora
    try:
        rl_key = f"rate:auth:reset:{email_normalized}"
        if not rate_limit(rl_key, 3, 3600):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes de recuperación. Intenta nuevamente en 1 hora."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open
    logger.info(f"Password reset requested for: {email_normalized}")
    result = await db.execute(
        select(User).where(func.lower(User.email) == email_normalized)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No existe un usuario con ese correo electrónico."
        )

    reset_token = secrets.token_urlsafe(32)
    # La columna es TIMESTAMP WITHOUT TIME ZONE, por lo que guardamos UTC naive.
    expiration = datetime.utcnow() + timedelta(hours=1)
    user.reset_token = reset_token
    user.reset_token_expiration = expiration
    await db.commit()
    logger.info(f"Password reset token generated for {email_normalized}")

    # Enviar correo de recuperación
    try:
        # Obtener nombre del perfil (si existe) o usar email como fallback
        full_name = "Usuario"
        if user.role == "CLIENT" and hasattr(user, 'client_profile') and user.client_profile:
            full_name = user.client_profile.full_name
        elif user.role == "PROVIDER" and hasattr(user, 'provider_profile') and user.provider_profile:
            full_name = user.provider_profile.full_name
        
        await email_service.send_password_reset_email(
            email=user.email,
            user_name=full_name,
            token=reset_token
        )
        logger.info(f"Password reset email sent to {email_normalized}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {email_normalized}: {e}")
        raise HTTPException(
            status_code=500,
            detail="No se pudo enviar el correo de recuperación. Intenta nuevamente."
        )

    return JSONResponse({"message": "Te enviamos instrucciones para restablecer tu contraseña a tu correo electrónico."})

# Endpoint para establecer nueva contraseña
@router.post("/set-new-password")
async def set_new_password(
    payload: SetNewPasswordRequest,
    db: AsyncSession = Depends(get_db_async)
):
    token = (payload.token or "").strip()
    new_password = payload.new_password or ""

    if not token:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    result = await db.execute(select(User).where(User.reset_token == token))
    user = result.scalar_one_or_none()

    token_expiration = user.reset_token_expiration if user else None
    if isinstance(token_expiration, str):
        try:
            token_expiration = datetime.fromisoformat(token_expiration.replace("Z", "+00:00"))
        except ValueError:
            token_expiration = None

    if isinstance(token_expiration, datetime) and token_expiration.tzinfo is None:
        # Compatibilidad: algunos registros históricos guardaron datetime naive.
        token_expiration = token_expiration.replace(tzinfo=timezone.utc)

    if not user or not isinstance(token_expiration, datetime):
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    if token_expiration < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    try:
        auth_service = AuthService(db)
        user.password = auth_service.get_password_hash(new_password)
        user.reset_token = None
        user.reset_token_expiration = None
        await db.commit()
        logger.info(f"Password reset completed for user {user.email}")
        return {"message": "Contraseña restablecida correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Unexpected error in set-new-password for token={token[:8]}...: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error during password reset"
        )


@router.post("/register-client", response_model=UserResponse)
async def register_client(
    request: Request,
    client_data: ClientRegister,
    db: AsyncSession = Depends(get_db_async)
):
    # Rate limit: 10 registros por IP por hora (clave separada de register-provider)
    try:
        client_ip = request.client.host if request.client else "unknown"
        rl_key = f"rate:auth:register:client:{client_ip}"
        if not rate_limit(rl_key, 10, 3600):
            raise HTTPException(
                status_code=429,
                detail="Demasiados intentos de registro. Intenta nuevamente en 1 hora."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    auth_service = AuthService(db)
    try:
        logger.info(f"Registering CLIENT: {client_data.email}")
        registration_source = _normalize_registration_source(getattr(client_data, "registration_source", None))
        user = await auth_service.register_client(client_data, registration_source=registration_source)
        return UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            status=user.status,
            created_at=user.created_at
        )
    except HTTPException as he:
        await db.rollback()
        logger.warning(f"Client registration failed: {he.detail}")
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Unexpected error registering client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al registrar cliente. Inténtalo nuevamente."
        )

@router.post("/register-provider", response_model=ProviderResponse)
async def register_provider(
    request: Request,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Register a new provider.

    Accepts JSON payloads used by the web frontend and keeps
    backward compatibility with multipart/form-data submissions.
    """
    auth_service = AuthService(db)
    try:
        content_type = request.headers.get("content-type", "")
        payload: dict[str, Any]
        avatar = None

        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            avatar = form.get("avatar")
            payload = {
                "email": form.get("email"),
                "password": form.get("password"),
                "run": form.get("run") or None,
                "full_name": form.get("full_name"),
                "phone": form.get("phone") or None,
                "bio": form.get("bio") or None,
                "terms_accepted": str(form.get("terms_accepted", "false")).lower() in {"true", "1", "on", "yes"},
                "email_opt_in": str(form.get("email_opt_in", "false")).lower() in {"true", "1", "on", "yes"},
            }

        # Validar primero — los 422 no consumen cupos de rate limit
        provider_data = ProviderRegister(**payload)

        # Rate limit: 10 intentos válidos por IP por hora (clave separada de register-client)
        try:
            client_ip = request.client.host if request.client else "unknown"
            rl_key = f"rate:auth:register:provider:{client_ip}"
            if not rate_limit(rl_key, 10, 3600):
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos de registro. Intenta nuevamente en 1 hora."
                )
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open

        logger.info(f"Registering PROVIDER: {provider_data.email}, RUN: {provider_data.run or 'N/A'}")

        if avatar and getattr(avatar, "filename", None):
            try:
                avatar_url = await auth_service.upload_provider_avatar(
                    provider_id=0,
                    file=avatar
                )
                provider_data.avatar = avatar_url
            except Exception as e:
                logger.warning(f"Avatar upload failed (non-critical): {e}")

        registration_source = _normalize_registration_source(getattr(provider_data, "registration_source", None))
        provider = await auth_service.register_provider(provider_data, registration_source=registration_source)
        logger.info(f"Provider registered successfully: ID={provider.id}")

        return ProviderResponse(
            id=provider.id,
            user_id=provider.user_id,
            run=provider.run,
            full_name=provider.full_name,
            phone=provider.phone,
            avatar=provider.avatar,
            bio=provider.bio,
            rating_avg=provider.rating_avg,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            email=provider.email,
            status=provider.status
        )

    except HTTPException as e:
        await db.rollback()
        logger.warning(f"Provider registration HTTP error {e.status_code}: {e.detail}")
        raise
    except ValidationError as e:
        await db.rollback()
        first_error = e.errors()[0] if e.errors() else {"msg": "Datos de registro inválidos"}
        logger.warning(f"Provider registration validation error: {first_error}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=first_error.get("msg", "Datos de registro inválidos")
        )
    except ValueError as e:
        await db.rollback()
        logger.warning(f"Provider registration validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        await db.rollback()
        logger.exception(f"Provider registration unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al registrar proveedor. Inténtalo nuevamente."
        )


@router.post("/login", response_model=Token)
async def login(form_data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db_async)):
    auth_service = AuthService(db)
    try:
        # Rate limiting: 5 intentos por email en 60s (fail-open)
        try:
            rl_key = f"rate:auth:login:{form_data.username.lower()}"
            if not rate_limit(rl_key, 5, 60):
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos de acceso. Intenta nuevamente en 1 minuto."
                )
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open: si Redis falla, no bloqueamos el login

        payload = await auth_service.login(form_data.username, form_data.password, form_data.role)
        _set_auth_cookies(response, payload["access_token"], payload.get("refresh_token"))
        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during login: {str(e)}"
        )

class GoogleLoginRequest(BaseModel):
    id_token: str
    role: str = "CLIENT"  # "CLIENT" | "PROVIDER"


class FacebookLoginRequest(BaseModel):
    access_token: str
    role: str = "CLIENT"
    email_hint: Optional[EmailStr] = None


@router.post("/oauth/google")
async def google_oauth(
    request: Request,
    response: Response,
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Login / registro con Google.

    El frontend debe obtener el id_token usando Google Sign-In SDK
    y enviarlo aquí. El backend valida con la API de Google y emite JWT propio.
    """
    try:
        rl_key = f"rate:auth:oauth:google:{request.client.host if request.client else 'unknown'}"
        if not rate_limit(rl_key, 10, 60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en 1 minuto.")
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    from app.services.oauth_service import OAuthService
    oauth_service = OAuthService(db)
    payload = await oauth_service.login_with_google(body.id_token, role=body.role)
    _set_auth_cookies(response, payload["access_token"], payload.get("refresh_token"))
    return payload


@router.post("/oauth/facebook")
async def facebook_oauth(
    request: Request,
    response: Response,
    body: FacebookLoginRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Login / registro con Facebook.

    El frontend debe obtener el access_token usando Facebook Login SDK
    y enviarlo aquí. El backend valida con Graph API de Facebook y emite JWT propio.
    """
    try:
        rl_key = f"rate:auth:oauth:facebook:{request.client.host if request.client else 'unknown'}"
        if not rate_limit(rl_key, 10, 60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en 1 minuto.")
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    from app.services.oauth_service import OAuthService
    oauth_service = OAuthService(db)
    payload = await oauth_service.login_with_facebook(
        body.access_token,
        role=body.role,
        email_hint=body.email_hint,
    )
    _set_auth_cookies(response, payload["access_token"], payload.get("refresh_token"))
    return payload

class AcceptTermsRequest(BaseModel):
    email_opt_in: bool = False


@router.patch("/accept-terms")
async def accept_terms(
    body: AcceptTermsRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Marca los T&C como aceptados para el usuario actual.
    Llamar desde la página terms-acceptance (flujo OAuth) o registro.
    """
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user.terms_accepted = True
    user.terms_accepted_at = datetime.now()
    user.email_opt_in = body.email_opt_in
    await db.commit()
    return {"message": "Términos aceptados correctamente", "terms_accepted": True}


class SendVerificationEmailRequest(BaseModel):
    email: EmailStr
    source: Optional[Literal["web", "mobile"]] = "web"


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class WebSessionFromTokenRequest(BaseModel):
    token: str


RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
RISC_CONFIG_CACHE_KEY = "risc:google:config"
RISC_JWKS_CACHE_KEY = "risc:google:jwks"
RISC_JTI_CACHE_PREFIX = "risc:event:jti:"


async def _fetch_json(url: str, timeout_seconds: int = 10) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=400, detail="No se pudo obtener configuración RISC")
            return await resp.json()


async def _get_risc_config() -> dict[str, Any]:
    cached = cache_get(RISC_CONFIG_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("issuer") and cached.get("jwks_uri"):
        return cached

    config = await _fetch_json(RISC_CONFIG_URL)
    cache_set(RISC_CONFIG_CACHE_KEY, config, ttl=6 * 60 * 60)
    return config


async def _get_risc_jwks(jwks_uri: str) -> dict[str, Any]:
    cached = cache_get(RISC_JWKS_CACHE_KEY)
    if isinstance(cached, dict) and isinstance(cached.get("keys"), list):
        return cached

    jwks = await _fetch_json(jwks_uri)
    cache_set(RISC_JWKS_CACHE_KEY, jwks, ttl=60 * 60)
    return jwks


def _extract_risc_token_from_request(request: Request, body_raw: bytes) -> Optional[str]:
    content_type = (request.headers.get("content-type") or "").lower()
    raw = (body_raw or b"").decode("utf-8", errors="ignore").strip()

    # Formato push típico: JWT plano en el body
    if raw and "." in raw and (content_type.startswith("application/secevent+jwt") or content_type.startswith("text/plain")):
        return raw

    # Fallback robusto: body JSON con token en llaves conocidas
    if raw and raw.startswith("{"):
        try:
            payload = json.loads(raw)
            for key in ("token", "jwt", "signed_event_token", "secevent"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except json.JSONDecodeError:
            return None

    # Último fallback: si parece JWT, aceptarlo
    if raw and raw.count(".") >= 2:
        return raw

    return None


def _audience_matches(aud_claim: Any, allowed: set[str]) -> bool:
    if not allowed:
        return False
    if isinstance(aud_claim, str):
        return aud_claim in allowed
    if isinstance(aud_claim, list):
        return any(isinstance(item, str) and item in allowed for item in aud_claim)
    return False


def _get_subject_identifiers(event_payload: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    subject = event_payload.get("subject") or {}
    if not isinstance(subject, dict):
        return None, None
    google_sub = subject.get("sub") if isinstance(subject.get("sub"), str) else None
    email = subject.get("email") if isinstance(subject.get("email"), str) else None
    return google_sub, email


async def _resolve_google_users_for_risc(db: AsyncSession, event_payload: dict[str, Any]) -> list[User]:
    google_sub, email = _get_subject_identifiers(event_payload)
    users: list[User] = []

    if google_sub:
        result = await db.execute(
            select(User).where(User.oauth_provider == "google", User.oauth_id == google_sub)
        )
        users = result.scalars().all()

    if users:
        return users

    if email:
        result = await db.execute(
            select(User).where(User.oauth_provider == "google", User.email == email)
        )
        return result.scalars().all()

    return []


def _revoke_all_sessions_for_user(user_id: int) -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl_seconds = int(((settings.REFRESH_TOKEN_EXPIRE_DAYS or 30) + 1) * 24 * 60 * 60)
    cache_set(f"security:revoke:user:{user_id}:after", now_ts, ttl=ttl_seconds)


async def _handle_risc_event(db: AsyncSession, event_type: str, event_payload: dict[str, Any]) -> None:
    users = await _resolve_google_users_for_risc(db, event_payload)
    if not users:
        return

    if event_type in {
        "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked",
        "https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked",
        "https://schemas.openid.net/secevent/oauth/event-type/token-revoked",
        "https://schemas.openid.net/secevent/risc/event-type/account-credential-change-required",
    }:
        for user in users:
            _revoke_all_sessions_for_user(user.id)
        return

    if event_type == "https://schemas.openid.net/secevent/risc/event-type/account-disabled":
        reason = (event_payload.get("reason") or "").lower()
        if reason in {"hijacking", "bulk-account", ""}:
            for user in users:
                _revoke_all_sessions_for_user(user.id)
        return


@router.post("/send-verification-email")
async def send_verification_email(
    body: SendVerificationEmailRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Envía (o reenvía) el email de verificación al usuario registrado."""
    from app.services.email_service import get_email_service

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user and not user.email_verified:
        token = secrets.token_urlsafe(32)
        user.email_verification_token = token
        user.email_verification_expiration = datetime.now() + timedelta(hours=24)
        await db.commit()

        source = _normalize_registration_source(body.source)
        verification_link = (
            f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify-email?token={token}&source={source}"
        )
        try:
            email_svc = get_email_service()
            user_name = body.email.split("@")[0]
            await email_svc.send_verification_email(body.email, user_name, verification_link)
        except Exception as exc:
            logger.warning(f"Verification email send failed (non-critical): {exc}")

    # Respuesta genérica — no revelar si el correo existe
    return {"message": "Si la cuenta existe y no está verificada, recibirás un correo de verificación."}


@router.get("/verify-email")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Verifica el email del usuario usando el token recibido por correo."""
    result = await db.execute(
        select(User).where(User.email_verification_token == token)
    )
    user = result.scalar_one_or_none()

    if not user or not user.email_verification_expiration:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    if user.email_verification_expiration < datetime.now():
        raise HTTPException(status_code=400, detail="El enlace de verificación ha expirado. Solicita uno nuevo.")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expiration = None
    await db.commit()

    return {"message": "Correo verificado correctamente. Ya puedes iniciar sesión."}


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: UserResponse = Depends(get_current_active_user)
):
    """
    Obtener información del usuario actual
    """
    return current_user


@router.post("/risc/events", status_code=202)
async def receive_risc_security_event(
    request: Request,
    db: AsyncSession = Depends(get_db_async),
):
    """Receptor de eventos RISC (Cross-Account Protection) enviado por Google.

    Requisitos Google:
    - Validar firma con jwks_uri de .well-known/risc-configuration.
    - Validar aud (OAuth client IDs de la app) e iss.
    - No validar exp (eventos históricos).
    - Responder HTTP 202 cuando el token es válido.
    """
    body_raw = await request.body()
    token = _extract_risc_token_from_request(request, body_raw)
    if not token:
        raise HTTPException(status_code=400, detail="Security event token faltante o inválido")

    risc_config = await _get_risc_config()
    issuer = risc_config.get("issuer")
    jwks_uri = risc_config.get("jwks_uri")
    if not issuer or not jwks_uri:
        raise HTTPException(status_code=400, detail="Configuración RISC inválida")

    jwks = await _get_risc_jwks(jwks_uri)
    keys = jwks.get("keys") or []
    if not isinstance(keys, list):
        raise HTTPException(status_code=400, detail="JWKS inválido")

    try:
        header = pyjwt.get_unverified_header(token)
        kid = header.get("kid")
    except Exception:
        raise HTTPException(status_code=400, detail="Header JWT inválido")

    if not kid:
        raise HTTPException(status_code=400, detail="JWT sin kid")

    jwk_candidate = next((k for k in keys if isinstance(k, dict) and k.get("kid") == kid), None)
    if not jwk_candidate:
        raise HTTPException(status_code=400, detail="No se encontró certificado para kid")

    try:
        public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk_candidate))
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo construir clave pública")

    allowed_client_ids = {cid for cid in (settings.RISC_GOOGLE_CLIENT_IDS or []) if cid}
    if settings.OAUTH_GOOGLE_CLIENT_ID:
        allowed_client_ids.add(settings.OAUTH_GOOGLE_CLIENT_ID)
    if not allowed_client_ids:
        raise HTTPException(status_code=500, detail="No hay client IDs configurados para validar RISC")

    try:
        claims = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": False},
            issuer=issuer,
            audience=list(allowed_client_ids),
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Token RISC inválido")

    # Dedupe por jti para evitar reprocesar reintentos de entrega.
    event_jti = claims.get("jti")
    if isinstance(event_jti, str) and event_jti:
        dedupe_key = f"{RISC_JTI_CACHE_PREFIX}{event_jti}"
        if cache_get(dedupe_key) is not None:
            return {"status": "duplicate_ignored"}
        cache_set(dedupe_key, "1", ttl=7 * 24 * 60 * 60)

    # Validación adicional defensiva de audiencia.
    if not _audience_matches(claims.get("aud"), allowed_client_ids):
        raise HTTPException(status_code=400, detail="Audience no permitida")

    events_claim = claims.get("events") or {}
    if not isinstance(events_claim, dict) or not events_claim:
        raise HTTPException(status_code=400, detail="Claim events inválido")

    for event_type, event_payload in events_claim.items():
        if not isinstance(event_type, str) or not isinstance(event_payload, dict):
            continue
        try:
            await _handle_risc_event(db, event_type, event_payload)
        except Exception as exc:
            logger.warning(f"RISC event handling warning ({event_type}): {exc}")

    return {"status": "accepted"}


@router.post("/web-session")
async def create_web_session_from_token(
    request: Request,
    response: Response,
    body: WebSessionFromTokenRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Intercambia un access token válido por cookies HttpOnly de sesión web.

    Uso principal: bridge de pago desde app móvil hacia web.
    """
    auth_service = AuthService(db)
    from datetime import timedelta
    from app.models.provider import Provider
    from app.models.user import UserProfile

    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token requerido")

    # Rate limit: 20 intercambios por IP por minuto
    try:
        client_ip = request.client.host if request.client else "unknown"
        rl_key = f"rate:auth:web-session:{client_ip}"
        if not rate_limit(rl_key, 20, 60):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes. Intenta nuevamente en 1 minuto.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    if payload.get("token_type", "access") != "access":
        raise HTTPException(status_code=401, detail="Tipo de token inválido")

    jti = payload.get("jti")
    if jti:
        try:
            if cache_get(f"blacklist:jwt:{jti}") is not None:
                raise HTTPException(status_code=401, detail="Token revocado")
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open

    email = payload.get("sub")
    user_id = payload.get("user_id")
    if not email or not user_id:
        raise HTTPException(status_code=401, detail="Payload de token inválido")

    iat = payload.get("iat")
    if iat:
        try:
            cutoff = cache_get(f"security:revoke:user:{user_id}:after")
            if cutoff is not None and int(iat) <= int(cutoff):
                raise HTTPException(status_code=401, detail="Token invalidado por seguridad")
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open

    result = await db.execute(select(User).where(User.id == user_id, User.email == email))
    user = result.scalar_one_or_none()
    if not user or user.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Usuario inválido o inactivo")

    provider_id = None
    client_id = None
    if user.role == "PROVIDER":
        provider_result = await db.execute(select(Provider).where(Provider.user_id == user.id))
        provider = provider_result.scalar_one_or_none()
        if provider:
            provider_id = provider.id
    elif user.role == "CLIENT":
        client_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
        profile = client_result.scalar_one_or_none()
        if profile:
            client_id = profile.id

    token_payload = {
        "sub": user.email,
        "user_id": user.id,
        "role": user.role,
        "provider_id": provider_id,
        "client_id": client_id,
    }
    access_token = auth_service.create_access_token(
        data=token_payload,
        expires_delta=timedelta(minutes=auth_service.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = auth_service.create_refresh_token(data=token_payload)

    # One-time exchange: invalidar el access token entrante para reducir replay.
    if jti and payload.get("exp"):
        try:
            source_ttl = max(int(payload["exp"] - datetime.now(timezone.utc).timestamp()), 1)
            cache_set(f"blacklist:jwt:{jti}", "1", ttl=source_ttl)
        except Exception:
            pass  # fail-open

    _set_auth_cookies(response, access_token, refresh_token)

    return {
        "message": "Sesión web iniciada",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "provider_id": provider_id,
            "client_id": client_id,
            "has_premium": getattr(user, "has_premium", False),
        },
    }


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    body: Optional[RefreshTokenRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Emite un nuevo access token y rota refresh token.
    Compatibilidad: si no se envía refresh_token en body, acepta bearer access token legado.
    """
    auth_service = AuthService(db)
    from datetime import timedelta
    from app.models.provider import Provider
    from app.models.user import UserProfile

    # Compatibilidad hacia atrás:
    # - Preferir refresh token enviado en body.
    # - Si no viene, usar Authorization Bearer como fallback legacy.
    token_candidate = (body.refresh_token if body and body.refresh_token else None)
    if not token_candidate and request is not None:
        token_candidate = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token_candidate and credentials:
        token_candidate = credentials.credentials

    if not token_candidate:
        raise HTTPException(status_code=401, detail="Refresh token requerido")

    try:
        payload = jwt.decode(token_candidate, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token inválido o expirado")

    # Antireplay para refresh token: si ya fue usado/revocado, rechazar.
    if payload.get("token_type") == "refresh":
        refresh_jti = payload.get("jti")
        if refresh_jti:
            try:
                if cache_get(f"blacklist:refresh:{refresh_jti}") is not None:
                    raise HTTPException(status_code=401, detail="Refresh token revocado")
            except HTTPException:
                raise
            except Exception:
                pass  # fail-open

    # Si vino explícitamente refresh token, exigir tipo refresh.
    if (body and body.refresh_token) and payload.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Tipo de token inválido para refresh")

    # En fallback legacy (Authorization), solo permitimos token de acceso vigente.
    if (
        (not body or not body.refresh_token)
        and (request is None or not request.cookies.get(settings.REFRESH_COOKIE_NAME))
        and payload.get("token_type", "access") != "access"
    ):
        raise HTTPException(status_code=401, detail="Tipo de token inválido")

    email = payload.get("sub")
    user_id = payload.get("user_id")
    if not email or not user_id:
        raise HTTPException(status_code=401, detail="Payload de token inválido")

    iat = payload.get("iat")
    if iat:
        try:
            cutoff = cache_get(f"security:revoke:user:{user_id}:after")
            if cutoff is not None and int(iat) <= int(cutoff):
                raise HTTPException(status_code=401, detail="Token invalidado por seguridad")
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open

    # Rate limit: 60 renovaciones por usuario por minuto
    # Chat + notificaciones pueden disparar bursts concurrentes al volver con token vencido.
    try:
        rl_key = f"rate:auth:refresh:{user_id}"
        if not rate_limit(rl_key, 60, 60):
            raise HTTPException(
                status_code=429,
                detail="Demasiados refresh de token. Intenta nuevamente en 1 minuto."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    result = await db.execute(select(User).where(User.id == user_id, User.email == email))
    current_user = result.scalar_one_or_none()
    if not current_user or current_user.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Usuario inválido o inactivo")

    provider_id = None
    client_id = None

    if current_user.role == "PROVIDER":
        result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
        provider = result.scalar_one_or_none()
        if provider:
            provider_id = provider.id
    elif current_user.role == "CLIENT":
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
        profile = result.scalar_one_or_none()
        if profile:
            client_id = profile.id

    token_payload = {
        "sub": current_user.email,
        "user_id": current_user.id,
        "role": current_user.role,
        "provider_id": provider_id,
        "client_id": client_id,
    }
    access_token = auth_service.create_access_token(
        data=token_payload,
        expires_delta=timedelta(minutes=auth_service.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    rotated_refresh_token = auth_service.create_refresh_token(data=token_payload)

    # Rotación one-time: invalidar refresh token consumido hasta su expiración.
    if payload.get("token_type") == "refresh":
        refresh_jti = payload.get("jti")
        refresh_exp = payload.get("exp")
        if refresh_jti and refresh_exp:
            try:
                ttl = max(int(refresh_exp - datetime.now(timezone.utc).timestamp()), 1)
                cache_set(f"blacklist:refresh:{refresh_jti}", "1", ttl=ttl)
            except Exception:
                pass  # fail-open

    if response is not None:
        _set_auth_cookies(response, access_token, rotated_refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": rotated_refresh_token,
        "token_type": "bearer",
    }
