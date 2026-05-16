"""
Seed inicial de palabras bloqueadas para moderación de contenido
Script para poblar la base de datos con palabras prohibidas comunes

Uso:
    python -m app.scripts.seed_blocked_words
"""
import asyncio
import sys
from pathlib import Path

# Agregar directorio raíz al path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import select
from app.core.database import engine_async, async_session
from app.models.blocked_word import BlockedWord, WordCategory, SeverityLevel


# ─── Lista de palabras bloqueadas iniciales ──────────────────────────────────

BLOCKED_WORDS = [
    # SEXUAL - CRITICAL
    {"word": "puta", "category": WordCategory.SEXUAL, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "puto", "category": WordCategory.SEXUAL, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "prostituta", "category": WordCategory.SEXUAL, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "zorra", "category": WordCategory.SEXUAL, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "perra", "category": WordCategory.SEXUAL, "severity": SeverityLevel.MEDIUM, "language": "es"},
    
    # VIOLENCE - CRITICAL
    {"word": "matar", "category": WordCategory.VIOLENCE, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "asesinar", "category": WordCategory.VIOLENCE, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "violar", "category": WordCategory.VIOLENCE, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "golpear", "category": WordCategory.VIOLENCE, "severity": SeverityLevel.MEDIUM, "language": "es"},
    
    # HATE - CRITICAL
    {"word": "negro de mierda", "category": WordCategory.HATE, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "maricón", "category": WordCategory.HATE, "severity": SeverityLevel.CRITICAL, "language": "es"},
    {"word": "marica", "category": WordCategory.HATE, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "indio", "category": WordCategory.HATE, "severity": SeverityLevel.MEDIUM, "language": "es", "pattern": r"\bindio\b(?!\samericano)"},
    {"word": "sudaca", "category": WordCategory.HATE, "severity": SeverityLevel.HIGH, "language": "es"},
    
    # DRUGS - HIGH
    {"word": "cocaína", "category": WordCategory.DRUGS, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "coca", "category": WordCategory.DRUGS, "severity": SeverityLevel.MEDIUM, "language": "es", "pattern": r"\bcoca\b(?!\s?(cola|light))"},
    {"word": "marihuana", "category": WordCategory.DRUGS, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "droga", "category": WordCategory.DRUGS, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "drogas", "category": WordCategory.DRUGS, "severity": SeverityLevel.MEDIUM, "language": "es"},
    
    # FRAUD - CRITICAL
    {"word": "estafa", "category": WordCategory.FRAUD, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "estafador", "category": WordCategory.FRAUD, "severity": SeverityLevel.HIGH, "language": "es"},
    {"word": "robo", "category": WordCategory.FRAUD, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "ladron", "category": WordCategory.FRAUD, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "ladrón", "category": WordCategory.FRAUD, "severity": SeverityLevel.MEDIUM, "language": "es"},
    
    # SPAM - LOW/MEDIUM
    {"word": "bitcoin", "category": WordCategory.SPAM, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "forex", "category": WordCategory.SPAM, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "gana dinero", "category": WordCategory.SPAM, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "dinero facil", "category": WordCategory.SPAM, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "click aqui", "category": WordCategory.SPAM, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "click aquí", "category": WordCategory.SPAM, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "haz click", "category": WordCategory.SPAM, "severity": SeverityLevel.LOW, "language": "es"},
    
    # Groserías comunes - LOW/MEDIUM
    {"word": "mierda", "category": WordCategory.SEXUAL, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "mrd", "category": WordCategory.SEXUAL, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "pendejo", "category": WordCategory.HATE, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "pendeja", "category": WordCategory.HATE, "severity": SeverityLevel.MEDIUM, "language": "es"},
    {"word": "idiota", "category": WordCategory.HATE, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "imbécil", "category": WordCategory.HATE, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "estúpido", "category": WordCategory.HATE, "severity": SeverityLevel.LOW, "language": "es"},
    {"word": "estupido", "category": WordCategory.HATE, "severity": SeverityLevel.LOW, "language": "es"},
]


async def seed_blocked_words():
    """Insertar palabras bloqueadas iniciales en la base de datos"""
    print("🌱 Iniciando seed de palabras bloqueadas...")
    
    async with async_session() as db:
        try:
            # Verificar cuántas palabras ya existen
            stmt = select(BlockedWord)
            result = await db.execute(stmt)
            existing_words = result.scalars().all()
            
            if len(existing_words) > 0:
                print(f"⚠️  Ya existen {len(existing_words)} palabras bloqueadas en la base de datos.")
                response = input("¿Deseas agregar las palabras faltantes? (s/n): ")
                if response.lower() != 's':
                    print("❌ Seed cancelado por el usuario.")
                    return
            
            # Obtener palabras existentes para evitar duplicados
            existing_words_set = {w.word.lower() for w in existing_words}
            
            # Insertar nuevas palabras
            added_count = 0
            skipped_count = 0
            
            for word_data in BLOCKED_WORDS:
                word_lower = word_data["word"].lower()
                
                if word_lower in existing_words_set:
                    print(f"⏭️  Palabra '{word_data['word']}' ya existe, omitiendo...")
                    skipped_count += 1
                    continue
                
                blocked_word = BlockedWord(
                    word=word_lower,
                    pattern=word_data.get("pattern"),
                    category=word_data["category"],
                    severity=word_data["severity"],
                    language=word_data["language"],
                    is_active=True
                )
                
                db.add(blocked_word)
                added_count += 1
                print(f"✅ Agregada: {word_data['word']} ({word_data['severity'].value})")
            
            await db.commit()
            
            print(f"\n🎉 Seed completado:")
            print(f"   - Palabras agregadas: {added_count}")
            print(f"   - Palabras omitidas (ya existían): {skipped_count}")
            print(f"   - Total en BD: {len(existing_words) + added_count}")
            
        except Exception as e:
            print(f"❌ Error durante el seed: {e}")
            await db.rollback()
            raise


async def main():
    """Función principal"""
    try:
        await seed_blocked_words()
    finally:
        await engine_async.dispose()


if __name__ == "__main__":
    asyncio.run(main())
