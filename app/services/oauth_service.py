"""
Servicio de autenticación OAuth para Google y Facebook.

Flujo:
  1. Frontend usa SDK nativo (Google/Facebook) y obtiene token
  2. Frontend envía token al backend
  3. Backend valida token con el proveedor externo
  4. Backend obtiene info del usuario (email, nombre, avatar)
  5. Backend busca/crea usuario interno y retorna JWT propio

Manejo de conflictos:
  - Email nuevo → crear usuario
  - Email existente + sin OAuth → vincular proveedor OAuth
  - oauth_id ya registrado → login directo
"""

import logging
from typing import Optional
from datetime import datetime

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status

from app.models.user import User, UserProfile
from app.models.provider import Provider
from app.services.auth_service import AuthService
from app.services.email_service import email_service
from app.core.config import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/me"


class OAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.auth_service = AuthService(db)
        self.email_service = email_service

    # ─── Google ────────────────────────────────────────────────────────────────

    async def login_with_google(self, id_token: str, role: str = "CLIENT") -> dict:
        """Valida id_token de Google y retorna JWT interno."""
        user_info = await self._validate_google_token(id_token)
        return await self._get_or_create_oauth_user(
            oauth_provider="google",
            oauth_id=user_info["sub"],
            email=user_info.get("email"),
            full_name=user_info.get("name", ""),
            avatar_url=user_info.get("picture"),
            role=role,
        )

    async def _validate_google_token(self, id_token: str) -> dict:
        """Valida el id_token contra la API de Google y retorna el payload."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GOOGLE_TOKEN_INFO_URL,
                params={"id_token": id_token},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()

        if resp.status != 200 or data.get("error"):
            logger.warning(f"[OAUTH] Google token inválido: {data.get('error_description', data.get('error'))}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de Google inválido o expirado",
            )

        # Verificar audience (aud debe ser nuestro client_id)
        aud = data.get("aud", "")
        if settings.OAUTH_GOOGLE_CLIENT_ID and settings.OAUTH_GOOGLE_CLIENT_ID not in aud:
            logger.warning(f"[OAUTH] Google token audience incorrecto: {aud}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de Google no corresponde a esta aplicación",
            )

        if not data.get("email_verified", "false") in ("true", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email de Google no verificado",
            )

        return data

    # ─── Facebook ──────────────────────────────────────────────────────────────

    async def login_with_facebook(
        self,
        access_token: str,
        role: str = "CLIENT",
        email_hint: Optional[str] = None,
    ) -> dict:
        """Valida access_token de Facebook y retorna JWT interno."""
        user_info = await self._validate_facebook_token(access_token)
        normalized_hint = (email_hint or "").strip().lower() or None
        return await self._get_or_create_oauth_user(
            oauth_provider="facebook",
            oauth_id=user_info["id"],
            email=user_info.get("email") or normalized_hint,
            full_name=user_info.get("name", ""),
            avatar_url=user_info.get("picture", {}).get("data", {}).get("url"),
            role=role,
        )

    async def _validate_facebook_token(self, access_token: str) -> dict:
        """Valida el access_token contra Graph API de Facebook."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                FACEBOOK_GRAPH_URL,
                params={
                    "access_token": access_token,
                    "fields": "id,name,email,picture.type(large)",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()

        if resp.status != 200 or data.get("error"):
            err = data.get("error", {})
            logger.warning(f"[OAUTH] Facebook token inválido: {err.get('message')}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de Facebook inválido o expirado",
            )

        if "id" not in data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Respuesta de Facebook no contiene ID de usuario",
            )

        return data

    # ─── Lógica común: buscar/crear usuario ────────────────────────────────────

    async def _get_or_create_oauth_user(
        self,
        oauth_provider: str,
        oauth_id: str,
        email: Optional[str],
        full_name: str,
        avatar_url: Optional[str],
        role: str,
    ) -> dict:
        """
        Busca usuario por oauth_provider+oauth_id o email.
        Si no existe, lo crea.
        Retorna el mismo dict que AuthService.create_access_token produce.
        """
        normalized_role = role if role in ("CLIENT", "PROVIDER") else "CLIENT"

        # 1. Buscar por oauth_provider + oauth_id + rol (login directo)
        user = await self._find_user_by_oauth(oauth_provider, oauth_id, normalized_role)
        is_new_user = False

        if not user and email:
            # 2. Buscar por email + rol → vincular cuenta OAuth existente
            user = await self._find_user_by_email(email, normalized_role)
            if user:
                await self._link_oauth_to_user(user, oauth_provider, oauth_id, avatar_url)
                # No es nuevo, el email ya existía

        if not user:
            # 3. Crear nuevo usuario
            is_new_user = True
            if not email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"El proveedor {oauth_provider} no proporcionó email. "
                        "Verifica los permisos de la aplicación."
                    ),
                )
            user = await self._create_oauth_user(
                email=email,
                full_name=full_name,
                oauth_provider=oauth_provider,
                oauth_id=oauth_id,
                avatar_url=avatar_url,
                role=normalized_role,
            )
        else:
            # Asegurar que el perfil exista incluso si el usuario ya existía
            await self._ensure_profile_exists(user, full_name, avatar_url)

        if user.status == "SUSPENDED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cuenta suspendida. Contacta al soporte.",
            )

        # Recargar para asegurar que las relaciones estén al día
        await self.db.refresh(user)

        # Resolver provider_id / client_id para el token
        provider_id = None
        client_id = None
        
        if user.role == "PROVIDER":
            if not user.provider_profile:
                # Intento de carga manual si refresh falló por alguna razón
                result = await self.db.execute(select(Provider).where(Provider.user_id == user.id))
                user.provider_profile = result.scalar_one_or_none()
            
            if user.provider_profile:
                provider_id = user.provider_profile.id
                
        elif user.role == "CLIENT":
            if not user.client_profile:
                result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
                user.client_profile = result.scalar_one_or_none()
                
            if user.client_profile:
                client_id = user.client_profile.id

        token = self.auth_service.create_access_token(data={
            "sub": user.email,
            "user_id": user.id,
            "role": user.role,
            "provider_id": provider_id,
            "client_id": client_id,
        })
        refresh_token = self.auth_service.create_refresh_token(data={
            "sub": user.email,
            "user_id": user.id,
            "role": user.role,
            "provider_id": provider_id,
            "client_id": client_id,
        })

        return {
            "access_token": token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.id,
            "role": user.role,
            "status": user.status,
            "provider_id": provider_id,
            "client_id": client_id,
            "email": user.email,
            "name": full_name or (user.provider_profile.full_name if provider_id else None) or (user.client_profile.full_name if client_id else None),
            "avatar_url": avatar_url or user.oauth_avatar_url,
            "terms_accepted": user.terms_accepted,
            "is_new_user": is_new_user,
        }

    async def _ensure_profile_exists(self, user: User, full_name: Optional[str], avatar_url: Optional[str]):
        """Verifica que el perfil correspondiente al rol exista, si no, lo crea."""
        # Asegurar que tengamos un nombre para el perfil
        display_name = (full_name or "").strip()
        if not display_name:
            display_name = user.email.split("@")[0].capitalize()

        if user.role == "CLIENT":
            if not user.client_profile:
                # Doble check con consulta directa
                result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
                profile = result.scalar_one_or_none()
                if not profile:
                    profile = UserProfile(
                        user_id=user.id,
                        full_name=display_name,
                        avatar=avatar_url
                    )
                    self.db.add(profile)
                    await self.db.commit()
                    logger.info(f"[OAUTH] Perfil de cliente creado para usuario {user.id} ({display_name})")
                else:
                    user.client_profile = profile
        
        elif user.role == "PROVIDER":
            if not user.provider_profile:
                # Doble check con consulta directa
                result = await self.db.execute(select(Provider).where(Provider.user_id == user.id))
                provider_profile = result.scalar_one_or_none()
                if not provider_profile:
                    provider_profile = Provider(
                        user_id=user.id,
                        full_name=display_name,
                        avatar=avatar_url
                    )
                    self.db.add(provider_profile)
                    await self.db.commit()
                    logger.info(f"[OAUTH] Perfil de proveedor creado para usuario {user.id} ({display_name})")
                else:
                    user.provider_profile = provider_profile

    async def _find_user_by_oauth(self, provider: str, oauth_id: str, role: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_id == oauth_id,
                User.role == role,
            )
        )
        return result.scalar_one_or_none()

    async def _find_user_by_email(self, email: str, role: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.email == email, User.role == role)
        )
        return result.scalar_one_or_none()

    async def _link_oauth_to_user(
        self, user: User, provider: str, oauth_id: str, avatar_url: Optional[str]
    ):
        """Vincula un proveedor OAuth a un usuario existente."""
        user.oauth_provider = provider
        user.oauth_id = oauth_id
        if avatar_url and not user.oauth_avatar_url:
            user.oauth_avatar_url = avatar_url
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        logger.info(f"[OAUTH] Usuario {user.id} vinculado con {provider}")

    async def _create_oauth_user(
        self,
        email: str,
        full_name: Optional[str],
        oauth_provider: str,
        oauth_id: str,
        avatar_url: Optional[str],
        role: str,
    ) -> User:
        """Crea un nuevo usuario OAuth (sin password)."""
        if role not in ("CLIENT", "PROVIDER"):
            role = "CLIENT"

        # Asegurar que tengamos un nombre para el perfil
        display_name = (full_name or "").strip()
        if not display_name:
            display_name = email.split("@")[0].capitalize()

        new_user = User(
            email=email,
            password=None,       # usuarios OAuth no tienen password
            role=role,
            status="ACTIVE",
            email_verified=True, # email verificado por el proveedor OAuth
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
            oauth_avatar_url=avatar_url,
            terms_accepted=False,  # debe aceptar T&C en el primer acceso
            email_opt_in=False,
        )
        self.db.add(new_user)
        await self.db.flush()  # obtener id antes del commit

        # Crear perfil básico según rol
        if role == "CLIENT":
            profile = UserProfile(
                user_id=new_user.id,
                full_name=display_name,
                avatar=avatar_url,
            )
            self.db.add(profile)
        elif role == "PROVIDER":
            provider_profile = Provider(
                user_id=new_user.id,
                full_name=display_name,
                avatar=avatar_url,
            )
            self.db.add(provider_profile)

        await self.db.commit()
        await self.db.refresh(new_user)

        # Enviar correo de bienvenida
        # Usar parámetro `email` local — new_user puede expirar en futuros commits
        try:
            sent = await self.email_service.send_welcome_email(
                email=email,
                user_name=display_name,
                role=role
            )
            if sent:
                logger.info(f"[OAUTH] Welcome email sent to {email} (role={role})")
            else:
                logger.warning(f"[OAUTH] Welcome email NOT sent to {email} (returned False)")
        except Exception as e:
            logger.error(f"[OAUTH] Error enviando correo de bienvenida a {email}: {e}", exc_info=True)

        logger.info(f"[OAUTH] Nuevo usuario creado via {oauth_provider}: {email} (id={new_user.id})")
        return new_user
