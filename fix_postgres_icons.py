
import asyncio
import asyncpg

async def fix_icons_postgres():
    DB_CONFIG = {
        'host': 'dpg-d5sl1bv18n1s73fm8fag-a.virginia-postgres.render.com',
        'port': 5432,
        'database': 'dbbapp',
        'user': 'admin_bapp',
        'password': '4qzvfoo6NdCwUAv8gkvWhYUiOABq9KMH',
        'ssl': 'require'
    }

    ICON_MAP = {
        'Construcción': 'construct', 'Electricidad': 'flash', 'Plomería': 'water',
        'Fontanería': 'water', 'Carpintería': 'hammer', 'Pintura': 'brush',
        'Jardinería': 'leaf', 'Limpieza': 'sparkles', 'Mascotas': 'paw',
        'Reparaciones': 'build', 'Belleza': 'cut', 'Salud': 'medkit',
        'Educación': 'school', 'Transporte': 'car', 'Eventos': 'calendar',
        'Tecnología': 'laptop', 'Gastronomía': 'restaurant', 'Alimentos': 'restaurant',
        'Climatización': 'thermometer', 'Ferretería': 'color-fill', 'Mudanzas': 'bus',
        'Seguridad': 'shield-checkmark', 'Legales': 'briefcase', 'Veterinaria': 'paw',
        'Peluquería': 'cut', 'Barbería': 'cut', 'Clínica': 'medkit', 'Enfermería': 'medkit',
        'Gimnasio': 'fitness', 'Fútbol': 'football', 'Papelería': 'print'
    }

    try:
        print("🔗 Conectando a PostgreSQL...")
        conn = await asyncpg.connect(**DB_CONFIG)
        
        print("\n--- Corrigiendo Subcategorías (Service Categories) ---")
        services = await conn.fetch("SELECT id, name, icon FROM service_categories")
        
        count = 0
        for svc in services:
            svc_id = svc['id']
            svc_name = svc['name']
            current_icon = svc['icon'] or ''
            
            # Solo actualizar si el icono NO es una URL de Cloudinary
            if not current_icon.startswith('http'):
                target_icon = None
                for key, icon in ICON_MAP.items():
                    if key.lower() in svc_name.lower():
                        target_icon = icon
                        break
                
                if target_icon and current_icon != target_icon:
                    await conn.execute("UPDATE service_categories SET icon = $1 WHERE id = $2", target_icon, svc_id)
                    count += 1
        
        print(f"✅ Se actualizaron {count} subcategorías.")

        await conn.close()
        print("\n🚀 Proceso finalizado.")

    except Exception as e:
        print(f"❌ Error durante la ejecución: {e}")

if __name__ == '__main__':
    asyncio.run(fix_icons_postgres())
