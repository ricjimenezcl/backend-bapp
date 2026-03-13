import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import timezone, timedelta, datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.user import User, UserProfile
from app.models.provider import Provider
from app.schemas.user import ClientRegister, Token
from app.schemas.provider import ProviderRegister
from app.core.config import settings

EMAIL_ALREADY_REGISTERED = "Email already registered"
RUN_ALREADY_REGISTERED = "RUN already registered"

class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.SECRET_KEY = settings.SECRET_KEY
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = 120

    def verify_password(self, plain_password, hashed_password):
        # bcrypt solo admite hasta 72 bytes
        return self.pwd_context.verify(plain_password[:72], hashed_password)

    def get_password_hash(self, password):
        # bcrypt solo admite hasta 72 bytes
        return self.pwd_context.hash(password[:72])

    def create_access_token(self, data: dict, expires_delta: timedelta = None):
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        jti = uuid.uuid4().hex
        to_encode.update({"exp": expire, "iat": now, "jti": jti})
        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt

    async def authenticate_user(self, email: str, password: str):
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user or not self.verify_password(password, user.password):
            return False
        return user

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

    async def register_client(self, client_data: ClientRegister) -> User:
        # Verificar si el usuario ya existe
        result = await self.db.execute(select(User).where(User.email == client_data.email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=EMAIL_ALREADY_REGISTERED
            )
        
        # Crear usuario CLIENTE
        hashed_password = self.get_password_hash(client_data.password)
        
        user = User(
            email=client_data.email,
            password=hashed_password,
            role="CLIENT",
            status="ACTIVE",
            email_verified=False
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Crear perfil en user_profiles
        profile = UserProfile(
            user_id=user.id,
            full_name=client_data.full_name,
            phone=client_data.phone
        )
        
        self.db.add(profile)
        await self.db.commit()
        
        return user

    async def register_provider(self, provider_data: ProviderRegister) -> Provider:
        # Verificar si el usuario ya existe
        result = await self.db.execute(select(User).where(User.email == provider_data.email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=EMAIL_ALREADY_REGISTERED
            )
        
        # Verificar si el RUN ya existe
        result = await self.db.execute(select(Provider).where(Provider.run == provider_data.run))
        existing_provider = result.scalar_one_or_none()

        if existing_provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=RUN_ALREADY_REGISTERED
            )
        
        # Crear usuario PROVEEDOR
        hashed_password = self.get_password_hash(provider_data.password)
        
        user = User(
            email=provider_data.email,
            password=hashed_password,
            role="PROVIDER",
            status="ACTIVE",
            email_verified=False
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        # Crear perfil en providers
        provider = Provider(
            user_id=user.id,
            run=provider_data.run,
            full_name=provider_data.full_name,
            phone=provider_data.phone,
            bio=provider_data.bio,
            avatar=provider_data.avatar
        )
        
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        
        # Asignar campos adicionales para la respuesta (hack para cumplir con Pydantic si es necesario)
        provider.email = user.email
        provider.status = user.status
        
        return provider

    async def login(self, username: str, password: str) -> dict:
        user = await self.authenticate_user(username, password)
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
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id,
            "role": user.role,
            "email": user.email,
            "provider_id": provider_id,
            "client_id": client_id
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