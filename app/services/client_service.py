from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.models.user import User, UserProfile
from app.schemas.user import ClientRegister
from app.services.auth_service import AuthService

class ClientService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_client(self, client_data: ClientRegister):
        try:
            # Verificar si el usuario ya existe
            result = await self.db.execute(select(User).where(User.email == client_data.email))
            existing_user = result.scalar_one_or_none()

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            # Crear usuario CLIENTE
            auth_service = AuthService(self.db)
            hashed_password = auth_service.get_password_hash(client_data.password)
            
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

            # Crear perfil de CLIENTE (tabla user_profiles)
            profile = UserProfile(
                user_id=user.id,
                full_name=client_data.full_name,
                phone=client_data.phone
            )

            self.db.add(profile)
            await self.db.commit()

            return user

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Client registration failed: {str(e)}"
            )

    async def get_client_profile(self, user_id: int):
        """Obtener perfil completo de cliente"""
        from sqlalchemy.orm import selectinload
        
        # IMPORTANTE: En SQLAlchemy async, usar selectinload para eager loading
        # para evitar lazy loading que causa MissingGreenlet
        query = (
            select(User)
            .options(selectinload(User.client_profile))
            .where(User.id == user_id)
            .where(User.role == "CLIENT")
        )
        result = await self.db.execute(query)
        user = result.unique().scalar_one_or_none()
        
        if not user or not user.client_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client profile not found"
            )
            
        # Construir respuesta manualmente para asegurar estructura
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "created_at": user.created_at,
            "profile": {
                "id": user.client_profile.id,
                "user_id": user.client_profile.user_id,
                "full_name": user.client_profile.full_name,
                "phone": user.client_profile.phone,
                "avatar": user.client_profile.avatar,
                "rating_avg": user.client_profile.rating_avg
            }
        }

    async def update_client_profile(self, user_id: int, update_data):
        """Actualizar perfil de cliente"""
        # Verificar usuario y obtener perfil usando join
        query = (
            select(UserProfile)
            .join(User)
            .where(User.id == user_id)
            .where(User.role == "CLIENT")
        )
        result = await self.db.execute(query)
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client profile not found"
            )
            
        # Actualizar campos permitidos
        if update_data.full_name:
            profile.full_name = update_data.full_name
        if update_data.phone:
            profile.phone = update_data.phone
        if update_data.avatar:
            profile.avatar = update_data.avatar
            
        await self.db.commit()
        await self.db.refresh(profile)
        
        # Obtener usuario refrescado para respuesta completa
        user_result = await self.db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one()
        
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "created_at": user.created_at,
            "profile": {
                "id": profile.id,
                "user_id": profile.user_id,
                "full_name": profile.full_name,
                "phone": profile.phone,
                "avatar": profile.avatar,
                "rating_avg": profile.rating_avg
            }
        }