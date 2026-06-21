import os
import asyncio
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

async def test_simple_send():
    print("--- Prueba Directa de EmailService con Resend ---")
    
    # Asegurarnos de que el path sea correcto para importar app
    import sys
    sys.path.append(os.getcwd())
    
    from app.services.email_service import EmailService
    from app.core.config import settings
    
    if not settings.RESEND_API_KEY:
        print("❌ ERROR: RESEND_API_KEY no encontrada en el .env")
        return

    email_service = EmailService()
    
    # IMPORTANTE: Reemplaza con tu correo registrado en Resend
    target_email = "searchbapp@gmail.com" 
    
    print(f"Enviando prueba a: {target_email}...")
    
    # 1. Probar Bienvenida Cliente (Con los nuevos textos)
    print("\n1. Enviando Bienvenida Cliente...")
    success_client = await email_service.send_welcome_email(
        email=target_email,
        user_name="Juan Cliente BAPP",
        role="CLIENT"
    )
    print(f"{'✅ Enviado' if success_client else '❌ Falló'}")

    # 2. Probar Bienvenida Proveedor (Con los nuevos textos)
    print("\n2. Enviando Bienvenida Proveedor...")
    success_provider = await email_service.send_welcome_email(
        email=target_email,
        user_name="María Proveedora BAPP",
        role="PROVIDER"
    )
    print(f"{'✅ Enviado' if success_provider else '❌ Falló'}")

if __name__ == "__main__":
    asyncio.run(test_simple_send())
