import base64
import traceback
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.models.user import User
from app.models.provider import Provider, ServiceProvider
from app.schemas.provider import ProviderRegister, ServiceProviderCreate, ProviderUpdateRequest
from app.services.auth_service import AuthService
from app.infra.redis import redis_client
import json

class ProviderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_provider(self, provider_data: ProviderRegister):
        try:
            # Verificar si el usuario ya existe
            result = await self.db.execute(select(User).where(User.email == provider_data.email))
            existing_user = result.scalar_one_or_none()

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            # Verificar si el RUN ya existe
            result = await self.db.execute(select(Provider).where(Provider.run == provider_data.run))
            existing_provider = result.scalar_one_or_none()

            if existing_provider:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="RUN already registered"
                )

            # Crear usuario PROVEEDOR
            auth_service = AuthService(self.db)
            hashed_password = auth_service.get_password_hash(provider_data.password)
            
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

            # Procesar avatar
            avatar_binary = None
            if provider_data.avatar:
                try:
                    logger.info(f"🔧 Procesando avatar. Longitud base64: {len(provider_data.avatar)}")
                    
                    if provider_data.avatar.startswith('data:image'):
                        base64_data = provider_data.avatar.split(',', 1)[1]
                        logger.info("📷 Avatar es data URL, extraído base64")
                    else:
                        base64_data = provider_data.avatar
                        logger.info("📷 Avatar es base64 puro")
                    
                    padding = 4 - (len(base64_data) % 4)
                    if padding != 4:
                        base64_data += '=' * padding
                        logger.info(f"🔧 Padding agregado: {padding} caracteres")
                    
                    avatar_binary = base64.b64decode(base64_data)
                    logger.info(f"✅ Avatar decodificado a binario. Tamaño: {len(avatar_binary)} bytes")
                    
                except Exception as e:
                    logger.error(f"❌ Error procesando avatar: {e}")
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    avatar_binary = None

            # Crear perfil de PROVEEDOR
            provider = Provider(
                user_id=user.id,
                run=provider_data.run,
                full_name=provider_data.full_name,
                phone=provider_data.phone,
                bio=provider_data.bio,
                avatar=avatar_binary
            )

            logger.info(f"🔧 Creando provider con user_id: {user.id}")
            self.db.add(provider)
            await self.db.commit()
            
            # Obtener el provider con una consulta separada en lugar de refresh
            await self.db.refresh(provider)
            
            logger.info(f"✅ Provider creado exitosamente. ID: {provider.id}")

            return {
                "user_id": user.id,
                "provider_id": provider.id,
                "email": user.email,
                "full_name": provider.full_name,
                "message": "Provider registered successfully"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error(f"❌ Error en create_provider: {str(e)}")
            logger.error(f"❌ Traceback completo: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider registration failed: {str(e)}"
            )
    
    async def create_service_provider(self, service_data: ServiceProviderCreate):  # Usar el esquema corregido
        """Crear un nuevo servicio para un proveedor"""
        try:
            # Verificar que el proveedor existe
            result = await self.db.execute(
                select(Provider).where(Provider.id == service_data.provider_id)
            )
            provider = result.scalar_one_or_none()
            
            if not provider:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Provider not found"
                )

            # Validar que el proveedor tenga RUN y teléfono completados antes de publicar un servicio
            if not provider.run or not provider.phone:
                missing_fields = []
                if not provider.run: missing_fields.append("RUT (RUN)")
                if not provider.phone: missing_fields.append("teléfono")
                
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Perfil incompleto: Debe completar su {', '.join(missing_fields)} antes de publicar un servicio."
                )

            # Verificar que no existe un servicio duplicado
            result = await self.db.execute(
                select(ServiceProvider).where(
                    (ServiceProvider.provider_id == service_data.provider_id) &
                    (ServiceProvider.service_id == service_data.service_id)
                )
            )
            existing_service = result.scalar_one_or_none()
            
            if existing_service:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Service already registered for this provider"
                )

            # Crear el servicio del proveedor
            service_provider = ServiceProvider(
                provider_id=service_data.provider_id,
                service_id=service_data.service_id,
                business_name=service_data.business_name,
                description=service_data.description,
                address=service_data.address,
                latitude=service_data.latitude,
                longitude=service_data.longitude,
                phone=service_data.phone,
                hourly_rate=service_data.hourly_rate,
                is_available=True,
                validation_status="approved"
            )

            self.db.add(service_provider)
            await self.db.commit()
            await self.db.refresh(service_provider)

            # Invalidate provider caches (best-effort)
            try:
                await redis_client.delete(f"provider:services:{service_data.provider_id}")
                await redis_client.delete(f"provider:detailed:{service_data.provider_id}")
            except Exception:
                pass

            return service_provider

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Service provider creation failed: {str(e)}"
            )
        
    async def get_provider_by_user_id(self, user_id: int):
        """Obtener provider_id por user_id (Legacy)"""
        result = await self.db.execute(
            select(Provider).where(Provider.user_id == user_id)
        )
        provider = result.scalar_one_or_none()
        return provider

    async def get_provider_profile(self, user_id: int):
        """Obtener perfil completo de proveedor (incluye datos de usuario)"""
        query = (
            select(Provider)
            .join(User)
            .where(Provider.user_id == user_id)
        )
        result = await self.db.execute(query)
        provider = result.scalar_one_or_none()
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider profile not found"
            )
        
        # Inyectar campos del usuario para cumplir con ProviderResponse
        provider.email = provider.user.email
        provider.status = provider.user.status
        provider.is_profile_complete = bool(provider.run and provider.phone)
        
        # avatar es VARCHAR(500) con URL de Cloudinary, se devuelve directo
        return provider

    async def update_provider_profile(self, user_id: int, update_data: ProviderUpdateRequest):
        """Actualizar perfil de proveedor"""
        # Obtener proveedor y usuario
        query = (
            select(Provider)
            .join(User)
            .where(Provider.user_id == user_id)
        )
        result = await self.db.execute(query)
        provider = result.scalar_one_or_none()
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider profile not found"
            )
            
        # Actualizar campos de proveedor
        if update_data.full_name:
            provider.full_name = update_data.full_name
        if update_data.phone:
            provider.phone = update_data.phone
        if update_data.bio:
            provider.bio = update_data.bio
            
        # Actualizar avatar si se proporciona: subir a Cloudinary y guardar URL
        if update_data.avatar:
            try:
                from app.infra.storage.cloudinary_storage import CloudinaryStorage
                storage = CloudinaryStorage()
                
                # Decodificar base64 a bytes para subir
                if update_data.avatar.startswith('data:image'):
                    base64_data = update_data.avatar.split(',', 1)[1]
                else:
                    base64_data = update_data.avatar
                
                # Fix padding
                padding = 4 - (len(base64_data) % 4)
                if padding != 4:
                    base64_data += '=' * padding
                
                file_bytes = base64.b64decode(base64_data)
                
                # Subir a Cloudinary
                upload_result = await storage.upload_file(
                    file_bytes=file_bytes,
                    filename=f"avatar_{provider.id}.jpg",
                    folder=f"providers/{provider.id}/avatar",
                    resource_type="image",
                    public_id=f"provider_{provider.id}_avatar"
                )
                
                # Guardar URL en la BD (VARCHAR 500)
                provider.avatar = upload_result.secure_url
                logger.info(f"✅ Avatar subido a Cloudinary: {provider.avatar}")
            except Exception as e:
                logger.error(f"❌ Error subiendo avatar a Cloudinary: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
        
        # Validar lógica de campos únicos (RUN) si se actualiza
        if update_data.run and update_data.run != provider.run:
             # Verificar unicidad
             check_query = select(Provider).where(Provider.run == update_data.run)
             check_result = await self.db.execute(check_query)
             if check_result.scalar_one_or_none():
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail="RUN already registered"
                 )
             provider.run = update_data.run

        await self.db.commit()
        await self.db.refresh(provider)
        
        # Inyectar campos necesarios para ProviderResponse
        provider.email = provider.user.email
        provider.status = provider.user.status
        provider.is_profile_complete = bool(provider.run and provider.phone)

        # Invalidate provider caches (best-effort)
        try:
            await redis_client.delete(f"provider:profile:{provider.id}")
            await redis_client.delete(f"provider:detailed:{provider.id}")
            await redis_client.delete(f"provider:services:{provider.id}")
        except Exception:
            pass

        # Preparar respuesta
        provider.email = provider.user.email
        provider.status = provider.user.status
        
        # avatar es VARCHAR(500) con URL de Cloudinary, se devuelve directo
        return provider