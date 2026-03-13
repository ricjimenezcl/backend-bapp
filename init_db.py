#!/usr/bin/env python3
"""Initialize database tables from SQLAlchemy models."""

import asyncio
import sys
sys.path.insert(0, '.')

from app.core.database import engine_async, Base

async def main():
    print("\n" + "="*80)
    print("🗄️  CREANDO TABLAS DE BASE DE DATOS")
    print("="*80 + "\n")
    
    try:
        # Create all tables
        async with engine_async.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("\n✅ Tablas creadas exitosamente")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
