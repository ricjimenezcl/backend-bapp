import os
import asyncio
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv()

async def test_resend_integration():
    # Asegurarnos de que el path sea correcto para importar app
    import sys
    sys.path.append(os.getcwd())
    
    from app.services.email_service import EmailService
    from app.core.config import settings
    
    print(f"--- Prueba de integración con Resend ---")
    print(f"RESEND_API_KEY configurada: {'SÍ' if settings.RESEND_API_KEY else 'NO'}")
    
    email_service = EmailService()
    
    # IMPORTANTE: Resend en modo Sandbox solo permite enviar a tu propio correo de cuenta
    target_email = "rjimenezl@gmail.com" # Cambia esto si tu cuenta de Resend usa otro correo
    
    print(f"Intentando enviar correo de bienvenida a: {target_email}...")
    
    try:
        success = await email_service.send_welcome_email(
            email=target_email,
            user_name="Usuario de Prueba BAPP",
            role="CLIENT"
        )
        
        if success:
            print("✅ ¡ÉXITO! El correo fue enviado a través de Resend.")
            print("Revisa tu bandeja de entrada (y la carpeta de spam).")
        else:
            print("❌ FALLÓ el envío. Revisa los logs anteriores.")
            
    except Exception as e:
        print(f"❌ ERROR durante la ejecución: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_resend_integration())
