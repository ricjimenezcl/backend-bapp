import asyncio
from app.core.database import get_db_async
from app.models.user import User
from app.models.provider import Provider
from sqlalchemy import select

async def check():
    async for db in get_db_async():
        # Últimos usuarios
        result = await db.execute(
            select(User).order_by(User.id.desc()).limit(5)
        )
        users = result.scalars().all()
        
        print('Últimos 5 usuarios:')
        for u in users:
            print(f'  ID={u.id}, email={u.email}, role={u.role}, status={u.status}')
        
        # Últimos providers
        result2 = await db.execute(
            select(Provider).order_by(Provider.id.desc()).limit(5)
        )
        providers = result2.scalars().all()
        
        print('\nÚltimos 5 providers:')
        for p in providers:
            print(f'  ID={p.id}, user_id={p.user_id}, run={p.run}, full_name={p.full_name}')
        
        # Verificar si hay usuario sin provider
        result3 = await db.execute(select(User).where(User.role == 'PROVIDER'))
        all_provider_users = result3.scalars().all()
        
        print(f'\nTotal usuarios con rol PROVIDER: {len(all_provider_users)}')
        
        for user in all_provider_users:
            result4 = await db.execute(select(Provider).where(Provider.user_id == user.id))
            prov = result4.scalar_one_or_none()
            if not prov:
                print(f'  ⚠️  Usuario ID={user.id} ({user.email}) NO tiene registro en providers')
            else:
                print(f'  ✅ Usuario ID={user.id} ({user.email}) tiene provider ID={prov.id}')
        
        break

if __name__ == "__main__":
    asyncio.run(check())
