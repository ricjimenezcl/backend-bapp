
import asyncio
import os
import sys

# Añadir el path del backend
sys.path.append('/Users/rjimenezl/Documents/bapp/backend-bapp')

from app.core.database import SessionLocalAsync
from app.models.service_category import MainCategory, ServiceCategory
from sqlalchemy import select, update

async def check_and_fix_icons():
    # Mapeo de iconos (IonIcons) para categorías principales y servicios comunes
    ICON_MAP = {
        'Construcción': 'construct',
        'Electricidad': 'flash',
        'Plomería': 'water',
        'Fontanería': 'water',
        'Carpintería': 'hammer',
        'Pintura': 'brush',
        'Jardinería': 'leaf',
        'Limpieza': 'sparkles',
        'Mascotas': 'paw',
        'Reparaciones': 'build',
        'Belleza': 'cut',
        'Salud': 'medkit',
        'Educación': 'school',
        'Transporte': 'car',
        'Eventos': 'calendar',
        'Tecnología': 'laptop',
        'Gastronomía': 'restaurant',
        'Alimentos': 'restaurant',
        'Climatización': 'thermometer',
        'Ferretería': 'color-fill',
        'Mudanzas': 'bus',
        'Seguridad': 'shield-checkmark',
        'Legales': 'briefcase',
    }

    async with SessionLocalAsync() as session:
        # 1. Obtener todas las categorías principales
        result = await session.execute(select(MainCategory))
        main_cats = result.scalars().all()
        
        print("\n--- Categorías Principales ---")
        for cat in main_cats:
            print(f"ID: {cat.id} | Name: {cat.name} | Icon actual: {cat.icon}")
            
            # Si el icono está vacío o es nulo, o queremos forzar el mapeo
            target_icon = None
            for key, icon in ICON_MAP.items():
                if key.lower() in cat.name.lower():
                    target_icon = icon
                    break
            
            if target_icon and cat.icon != target_icon:
                print(f"  -> Actualizando a: {target_icon}")
                cat.icon = target_icon
        
        # 2. Obtener todos los servicios
        result_serv = await session.execute(select(ServiceCategory))
        services = result_serv.scalars().all()
        
        print("\n--- Servicios ---")
        for svc in services:
            # Solo actualizar si el icono está vacío o es el default
            if not svc.icon or svc.icon == 'construct-outline' or svc.icon == 'hammer':
                target_icon = None
                for key, icon in ICON_MAP.items():
                    if key.lower() in svc.name.lower():
                        target_icon = icon
                        break
                
                if target_icon and svc.icon != target_icon:
                    print(f"ID: {svc.id} | Name: {svc.name} | De '{svc.icon}' a '{target_icon}'")
                    svc.icon = target_icon

        await session.commit()
        print("\n✅ Proceso completado exitosamente.")

if __name__ == "__main__":
    asyncio.run(check_and_fix_icons())
