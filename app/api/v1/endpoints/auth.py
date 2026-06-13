import logging
from typing import Any

from app.dependencies import get_current_active_user

from fastapi import Body, APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import secrets
from datetime import datetime, timedelta, timezone
from app.models.user import User
from sqlalchemy.future import select
from app.core.database import get_db_async
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import UserResponse, ClientRegister, Token
from app.schemas.provider import ProviderRegister, ProviderResponse
from pydantic import BaseModel, EmailStr, ValidationError
from app.services.auth_service import AuthService
from app.core.config import settings
from app.core.redis import rate_limit, cache_set

logger = logging.getLogger(__name__)
security = HTTPBearer()

router = APIRouter()

class LoginRequest(BaseModel):
    """Schema para el login"""
    username: str
    password: str

# Endpoint para solicitar recuperación de contraseña
@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(get_current_active_user)
):
    """Invalida el token actual añadiéndolo a la blacklist de Redis."""
    try:
        payload = jwt.decode(
            credentials.credentials,
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
    return {"message": "Sesión cerrada correctamente"}


@router.post("/reset-password")
async def reset_password(
    request: Request,
    email: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db_async)
):
    # Rate limit: 3 solicitudes por email por hora
    try:
        rl_key = f"rate:auth:reset:{email.lower()}"
        if not rate_limit(rl_key, 3, 3600):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes de recuperación. Intenta nuevamente en 1 hora."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open
    logger.info(f"Password reset requested for: {email}")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        reset_token = secrets.token_urlsafe(32)
        expiration = datetime.now() + timedelta(hours=1)
        user.reset_token = reset_token
        user.reset_token_expiration = expiration
        await db.commit()
        logger.info(f"Password reset token generated for {email}")
    return JSONResponse({"message": "Si el correo existe, recibirás instrucciones para restablecer tu contraseña."})

# Endpoint para establecer nueva contraseña
@router.post("/set-new-password")
async def set_new_password(
    token: str = Body(...),
    new_password: str = Body(...),
    db: AsyncSession = Depends(get_db_async)
):
    result = await db.execute(select(User).where(User.reset_token == token))
    user = result.scalar_one_or_none()
    if not user or not user.reset_token_expiration or user.reset_token_expiration < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token inválido o expirado")
    auth_service = AuthService(db)
    user.password = auth_service.get_password_hash(new_password)
    user.reset_token = None
    user.reset_token_expiration = None
    await db.commit()
    logger.info(f"Password reset completed for user {user.email}")
    return {"message": "Contraseña restablecida correctamente"}

# (El router ya está definido arriba, no volver a definirlo)

@router.post("/register-client", response_model=UserResponse)
async def register_client(
    request: Request,
    client_data: ClientRegister,
    db: AsyncSession = Depends(get_db_async)
):
    # Rate limit: 5 registros por IP por hora
    try:
        client_ip = request.client.host if request.client else "unknown"
        rl_key = f"rate:auth:register:{client_ip}"
        if not rate_limit(rl_key, 5, 3600):
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
        user = await auth_service.register_client(client_data)
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
            detail=f"Client registration failed: {str(e)}"
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
    # Rate limit: 5 registros por IP por hora
    try:
        client_ip = request.client.host if request.client else "unknown"
        rl_key = f"rate:auth:register:{client_ip}"
        if not rate_limit(rl_key, 5, 3600):
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

        provider_data = ProviderRegister(**payload)
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

        provider = await auth_service.register_provider(provider_data)
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
            detail=f"Provider registration failed: {str(e)}"
        )


@router.post("/login", response_model=Token)
async def login(form_data: LoginRequest, db: AsyncSession = Depends(get_db_async)):
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

        return await auth_service.login(form_data.username, form_data.password)

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


@router.post("/oauth/google")
async def google_oauth(
    request: Request,
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
    return await oauth_service.login_with_google(body.id_token, role=body.role)


@router.post("/oauth/facebook")
async def facebook_oauth(
    request: Request,
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
    return await oauth_service.login_with_facebook(body.access_token, role=body.role)

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

        verification_link = (
            f"{settings.FRONTEND_URL}/auth/verify-email?token={token}"
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


@router.post("/refresh")
async def refresh_token(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Emite un nuevo access token si el actual es todavía válido.
    No requiere refresh token separado — extiende la sesión activa.
    """
    # Rate limit: 10 renovaciones por usuario por minuto
    try:
        rl_key = f"rate:auth:refresh:{current_user.id}"
        if not rate_limit(rl_key, 10, 60):
            raise HTTPException(
                status_code=429,
                detail="Demasiados refresh de token. Intenta nuevamente en 1 minuto."
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open

    auth_service = AuthService(db)
    from datetime import timedelta
    from sqlalchemy.future import select
    from app.models.provider import Provider
    from app.models.user import UserProfile

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

    access_token = auth_service.create_access_token(
        data={
            "sub": current_user.email,
            "user_id": current_user.id,
            "role": current_user.role,
            "provider_id": provider_id,
            "client_id": client_id
        },
        expires_delta=timedelta(minutes=auth_service.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}
