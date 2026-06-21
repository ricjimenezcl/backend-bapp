import os
import asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
import sys

# Cargar variables de entorno
load_dotenv()

# Añadir el path del backend para importar app
sys.path.append(os.getcwd())

from app.models.user import User
from app.models.provider import Provider
from app.services.auth_service import AuthService
from app.schemas.provider import ProviderRegister
from app.core.config import settings

async def test_provider_registration_flow():
    """
    Simula el registro de un proveedor y verifica el envío de correo de bienvenida.
    """
    # 1. Configurar base de datos temporal para la prueba
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    test_email = "rjimenezl@gmail.com" # DEPE SER TU CORREO DE RESEND
    
    print(f"\n--- Iniciando prueba de registro de Proveedor ---")
    print(f"Email objetivo: {test_email}")
    
    async with AsyncSessionLocal() as db:
        auth_service = AuthService(db)
        
        # 2. Limpieza previa (opcional, por si el usuario ya existe)
        print(f"Buscando si existe usuario previo con {test_email}...")
        result = await db.execute(select(User).where(User.email == test_email))
        old_user = result.scalar_one_or_none()
        if old_user:
            print(f"Eliminando registro previo de {test_email} para limpieza...")
            # En cascada debería borrar el provider, pero lo hacemos manual por seguridad
            await db.execute(delete(Provider).where(Provider.user_id == old_user.id))
            await db.execute(delete(User).where(User.id == old_user.id))
            await db.commit()
            print("Limpieza completada.")

        # 3. Datos del registro del proveedor
        provider_data = ProviderRegister(
            email=test_email,
            password="Password123",
            full_name="Proveedor de Prueba BAPP",
            phone="+56912345678",
            run="12345678-k",
            bio="Esta es una bio de prueba para verificar el flujo completo de Resend.",
            terms_accepted=True
        )

        # 4. Ejecutar el registro
        print("\nEjecutando auth_service.register_provider()...")
        print("Esto debería activar automáticamente el EmailService con la plantilla welcome_provider.")
        
        try:
            new_provider = await auth_service.register_provider(provider_data)
            print(f"✅ Registro en DB exitoso. Provider ID: {new_provider.id}")
            print(f"✅ El correo de bienvenida debería estar en camino a {test_email}.")
            print("\nRevisa tu bandeja de entrada en unos segundos.")
            
        except Exception as e:
            print(f"❌ Error durante el registro/envío: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if not os.getenv("RESEND_API_KEY"):
        print("❌ ERROR: RESEND_API_KEY no encontrada en el .env")
    else:
        asyncio.run(test_provider_registration_flow())
