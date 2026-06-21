
import asyncio
import sys
import os
from pathlib import Path

# Añadir el directorio raíz al path para poder importar app
sys.path.append(str(Path(__file__).resolve().parent))

from app.services.email_service import email_service
from app.core.config import settings

async def test_production_ses():
    print("🚀 Iniciando prueba de AWS SES en Producción...")
    print(f"📧 Remitente: {settings.SES_FROM_EMAIL}")
    print(f"🌎 Región: {settings.AWS_REGION}")
    
    # Dirección de destino (puedes cambiarla aquí o pasarla por argumento)
    target_email = input("Introduce un correo para recibir la prueba: ")
    
    if not target_email:
        print("❌ Error: Debes introducir un correo de destino.")
        return

    print(f"⏳ Enviando correo de bienvenida (Cliente)...")
    success = await email_service.send_welcome_email(
        email=target_email,
        user_name="Usuario de Prueba",
        role="CLIENT"
    )
    
    if success:
        print("✅ Correo de Bienvenida enviado correctamente.")
    else:
        print("❌ Error al enviar el correo. Revisa los logs y tus credenciales en el .env")

    print(f"\n⏳ Enviando correo de reserva (Confirmación)...")
    booking_data = {
        "service_name": "Servicio de Prueba BAPP",
        "booking_date": "21 de Junio, 2026 - 15:00",
        "other_party_name": "Proveedor Estrella",
        "location": "Avenida Siempre Viva 742"
    }
    
    success_booking = await email_service.send_booking_created(
        client_email=target_email,
        provider_email=target_email, # Enviamos ambos al mismo para la prueba
        data=booking_data
    )

    if success_booking:
        print("✅ Correos de Reserva enviados correctamente.")
    else:
        print("❌ Error al enviar los correos de reserva.")

    print("\n🏁 Prueba finalizada.")

if __name__ == "__main__":
    if not settings.AWS_ACCESS_KEY_ID:
        print("⚠️  ERROR: AWS_ACCESS_KEY_ID no encontrada en el entorno.")
    else:
        asyncio.run(test_production_ses())
