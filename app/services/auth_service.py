import logging
import secrets
import uuid
from datetime import timedelta, datetime, timezone

from jose import JWTError, jwt

logger = logging.getLogger(__name__)
from passlib.context import CryptContext
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.user import User, UserProfile
from app.models.provider import Provider
from app.schemas.user import ClientRegister, Token
from app.schemas.provider import ProviderRegister
from app.core.config import settings
from app.services.email_service import email_service
from app.utils.chile_validators import normalize_phone

EMAIL_ALREADY_REGISTERED = "Email already registered"
RUN_ALREADY_REGISTERED = "RUN already registered"
PHONE_ALREADY_REGISTERED = "Phone already registered"

class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.SECRET_KEY = settings.SECRET_KEY
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = 120
        self.REFRESH_TOKEN_EXPIRE_DAYS = getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 30)

    def verify_password(self, plain_password, hashed_password):
        # bcrypt solo admite hasta 72 bytes
        return self.pwd_context.verify(plain_password[:72], hashed_password)

    def get_password_hash(self, password):
        # bcrypt solo admite hasta 72 bytes
        return self.pwd_context.hash(password[:72])

    def create_access_token(self, data: dict, expires_delta: timedelta = None, token_type: str = "access"):
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        jti = uuid.uuid4().hex
        to_encode.update({"exp": expire, "iat": now, "jti": jti, "token_type": token_type})
        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt

    def create_refresh_token(self, data: dict, expires_delta: timedelta = None):
        if expires_delta:
            refresh_exp = expires_delta
        else:
            refresh_exp = timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
        return self.create_access_token(data=data, expires_delta=refresh_exp, token_type="refresh")

    async def authenticate_user(self, email: str, password: str, role: str | None = None):
        normalized_email = (email or "").strip().lower()
        query = select(User).where(func.lower(func.trim(User.email)) == normalized_email)

        normalized_role = role.upper() if role else None
        if normalized_role:
            query = query.where(User.role == normalized_role)

        result = await self.db.execute(query)
        users = result.scalars().all()

        if not users:
            return False

        valid_users = [
            user for user in users
            if user.password and self.verify_password(password, user.password)
        ]

        if not valid_users:
            return False

        verified_users = [user for user in valid_users if bool(user.email_verified)]
        if not verified_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "EMAIL_NOT_VERIFIED",
                    "message": "Debes verificar tu correo electrónico para iniciar sesión.",
                },
            )

        if not normalized_role and len(verified_users) > 1:
            roles = sorted({u.role for u in verified_users})
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ROLE_SELECTION_REQUIRED",
                    "message": "Email asociado a múltiples perfiles",
                    "roles": roles,
                },
            )

        return verified_users[0]

    async def register_user(self, user_data):
        """Deprecated: Use register_client or register_provider instead"""
        # Check if user exists
        result = await self.db.execute(select(User).where(User.email == user_data.email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(status_code=400, detail=EMAIL_ALREADY_REGISTERED)
        
        hashed_password = self.get_password_hash(user_data.password)
        user = User(
            email=user_data.email,
            password=hashed_password,
            role=user_data.role,
            status="ACTIVE"
        )
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        return user

    async def register_client(self, client_data: ClientRegister, registration_source: str = "web") -> User:
        # Verificar si el usuario ya existe
        normalized_email = client_data.email.strip().lower()
        normalized_phone = normalize_phone(client_data.phone) if client_data.phone else None
        logger.info("register_client attempt email=%s phone=%s", normalized_email, normalized_phone or 'N/A')
        result = await self.db.execute(
            select(User).where(
                func.lower(func.trim(User.email)) == normalized_email,
                User.role == "CLIENT"
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            logger.warning(
                "register_client duplicate email incoming=%s existing_user_id=%s existing_email=%s role=%s status=%s",
                client_data.email,
                existing_user.id,
                existing_user.email,
                existing_user.role,
                existing_user.status,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=EMAIL_ALREADY_REGISTERED
            )
        
        # Verificar si el teléfono ya existe en perfiles de cliente
        result = await self.db.execute(
            select(UserProfile).where(func.replace(func.trim(UserProfile.phone), ' ', '') == (normalized_phone.replace(' ', '') if normalized_phone else None))
        )
        existing_profile = result.scalar_one_or_none()
        if existing_profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PHONE_ALREADY_REGISTERED
            )
        
        # Crear usuario CLIENTE
        hashed_password = self.get_password_hash(client_data.password)
        
        user = User(
            email=normalized_email,
            password=hashed_password,
            role="CLIENT",
            status="ACTIVE",
            email_verified=False,
            email_verification_token=secrets.token_urlsafe(32),
            email_verification_expiration=datetime.utcnow() + timedelta(hours=24),
            terms_accepted=getattr(client_data, 'terms_accepted', False),
            terms_accepted_at=datetime.utcnow() if getattr(client_data, 'terms_accepted', False) else None,
            email_opt_in=getattr(client_data, 'email_opt_in', False),
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        # Guardar antes del segundo commit — expire_on_commit expira user
        user_email = user.email
        user_id = user.id
        verification_token = user.email_verification_token
        
        # Crear perfil en user_profiles
        profile = UserProfile(
            user_id=user_id,
            full_name=client_data.full_name,
            phone=normalized_phone or client_data.phone
        )
        
        self.db.add(profile)
        await self.db.commit()
        
        # Enviar correo de bienvenida (usar variables locales — user está expirado)
        try:
            sent = await email_service.send_welcome_email(
                email=user_email,
                user_name=client_data.full_name,
                role="CLIENT"
            )
            if sent:
                logger.info(f"Welcome email sent to CLIENT {user_email}")
            else:
                logger.warning(f"Welcome email NOT sent to CLIENT {user_email} (send_welcome_email returned False)")
        except Exception as e:
            logger.error(f"Error sending welcome email to CLIENT {user_email}: {e}", exc_info=True)

        # Enviar correo de verificación de cuenta
        try:
            source = "mobile" if registration_source == "mobile" else "web"
            verification_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify-email?token={verification_token}&source={source}"
            sent = await email_service.send_verification_email(
                email=user_email,
                user_name=client_data.full_name,
                verification_link=verification_link,
            )
            if sent:
                logger.info(f"Verification email sent to CLIENT {user_email}")
            else:
                logger.warning(f"Verification email NOT sent to CLIENT {user_email}")
        except Exception as e:
            logger.error(f"Error sending verification email to CLIENT {user_email}: {e}", exc_info=True)
        
        return user

    async def register_provider(self, provider_data: ProviderRegister, registration_source: str = "web") -> Provider:
        # Verificar si el usuario ya existe
        normalized_email = provider_data.email.strip().lower()
        normalized_phone = normalize_phone(provider_data.phone) if provider_data.phone else None
        normalized_run = provider_data.run
        logger.info("register_provider attempt email=%s run=%s phone=%s", normalized_email, normalized_run or 'N/A', normalized_phone or 'N/A')

        # Prioridad: RUN -> teléfono -> email
        if normalized_run:
            result = await self.db.execute(select(Provider).where(Provider.run == normalized_run))
            existing_provider = result.scalar_one_or_none()
            if existing_provider:
                logger.warning(
                    "register_provider duplicate run incoming=%s existing_provider_id=%s existing_run=%s",
                    normalized_run,
                    existing_provider.id,
                    existing_provider.run,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=RUN_ALREADY_REGISTERED
                )

        if normalized_phone:
            result = await self.db.execute(
                select(Provider).where(func.replace(func.trim(Provider.phone), ' ', '') == normalized_phone.replace(' ', ''))
            )
            existing_provider_phone = result.scalar_one_or_none()
            if existing_provider_phone:
                logger.warning(
                    "register_provider duplicate phone incoming=%s existing_provider_id=%s existing_phone=%s",
                    normalized_phone,
                    existing_provider_phone.id,
                    existing_provider_phone.phone,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PHONE_ALREADY_REGISTERED
                )

        result = await self.db.execute(
            select(User).where(
                func.lower(func.trim(User.email)) == normalized_email,
                User.role == "PROVIDER"
            )
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            logger.warning(
                "register_provider duplicate email incoming=%s existing_user_id=%s existing_email=%s role=%s status=%s",
                provider_data.email,
                existing_user.id,
                existing_user.email,
                existing_user.role,
                existing_user.status,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=EMAIL_ALREADY_REGISTERED
            )
        
        # Crear usuario PROVEEDOR
        hashed_password = self.get_password_hash(provider_data.password)
        
        user = User(
            email=normalized_email,
            password=hashed_password,
            role="PROVIDER",
            status="ACTIVE",
            email_verified=False,
            email_verification_token=secrets.token_urlsafe(32),
            email_verification_expiration=datetime.utcnow() + timedelta(hours=24),
            terms_accepted=getattr(provider_data, 'terms_accepted', False),
            terms_accepted_at=datetime.utcnow() if getattr(provider_data, 'terms_accepted', False) else None,
            email_opt_in=getattr(provider_data, 'email_opt_in', False),
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        # Guardar antes del segundo commit — expire_on_commit expira user
        user_email = user.email
        user_id = user.id
        verification_token = user.email_verification_token
        
        # Crear perfil en providers
        provider = Provider(
            user_id=user_id,
            run=normalized_run,
            full_name=provider_data.full_name,
            phone=normalized_phone or provider_data.phone,
            bio=provider_data.bio,
            avatar=provider_data.avatar
        )
        
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        
        # Enviar correo de bienvenida (usar variables locales — user está expirado)
        try:
            sent = await email_service.send_welcome_email(
                email=user_email,
                user_name=provider_data.full_name,
                role="PROVIDER"
            )
            if sent:
                logger.info(f"Welcome email sent to PROVIDER {user_email}")
            else:
                logger.warning(f"Welcome email NOT sent to PROVIDER {user_email} (send_welcome_email returned False)")
        except Exception as e:
            logger.error(f"Error sending welcome email to PROVIDER {user_email}: {e}", exc_info=True)

        # Enviar correo de verificación de cuenta
        try:
            source = "mobile" if registration_source == "mobile" else "web"
            verification_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify-email?token={verification_token}&source={source}"
            sent = await email_service.send_verification_email(
                email=user_email,
                user_name=provider_data.full_name,
                verification_link=verification_link,
            )
            if sent:
                logger.info(f"Verification email sent to PROVIDER {user_email}")
            else:
                logger.warning(f"Verification email NOT sent to PROVIDER {user_email}")
        except Exception as e:
            logger.error(f"Error sending verification email to PROVIDER {user_email}: {e}", exc_info=True)

        # Asignar campos adicionales para la respuesta
        # (user expirado tras commit — usar variables locales)
        await self.db.refresh(user)
        provider.email = user.email
        provider.status = user.status
        
        return provider

    async def login(self, username: str, password: str, role: str | None = None) -> dict:
        user = await self.authenticate_user(username, password, role)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Obtener IDs específicos
        provider_id = None
        client_id = None
        
        if user.role == "PROVIDER":
            result = await self.db.execute(select(Provider).where(Provider.user_id == user.id))
            provider = result.scalar_one_or_none()
            if provider:
                provider_id = provider.id
        
        elif user.role == "CLIENT":
            result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
            profile = result.scalar_one_or_none()
            if profile:
                client_id = profile.id
        
        # Crear Token JWT Real
        access_token_expires = timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        token_payload = {
            "sub": user.email,
            "user_id": user.id,
            "role": user.role,
            "provider_id": provider_id,
            "client_id": client_id
        }
        access_token = self.create_access_token(
            data=token_payload, expires_delta=access_token_expires
        )
        refresh_token = self.create_refresh_token(data=token_payload)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.id,
            "role": user.role,
            "status": user.status,
            "email": user.email,
            "provider_id": provider_id,
            "client_id": client_id,
            "terms_accepted": user.terms_accepted,
        }
    
    async def upload_provider_avatar(self, provider_id: int, file) -> str:
        """
        Upload provider avatar to Cloudinary and return the URL.
        
        Args:
            provider_id: Provider ID
            file: UploadFile from FastAPI
            
        Returns:
            Cloudinary URL of the uploaded image
        """
        from app.infra.storage import get_storage
        
        # Read file content
        content = await file.read()
        
        # Validate file size (max 5MB for avatars)
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Avatar file too large. Maximum size: 5MB"
            )
        
        # Validate MIME type
        allowed_mimes = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
        if file.content_type not in allowed_mimes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(allowed_mimes)}"
            )
        
        try:
            # Upload to Cloudinary
            storage = get_storage()
            folder = f"providers/{provider_id}/avatar"
            upload_result = await storage.upload_file(
                file_bytes=content,
                filename=file.filename,
                folder=folder,
                resource_type="image"
            )
            
            return upload_result.secure_url
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Avatar upload failed: {str(e)}"
            )