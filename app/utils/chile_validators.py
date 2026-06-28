"""
app/utils/chile_validators.py

Validadores y normalizadores para datos específicos de Chile.
Fuente única de verdad — importar desde aquí en todos los schemas y servicios.
"""

import re

# ── Constantes ────────────────────────────────────────────────────────────────

_PHONE_PATTERN = re.compile(r'^(\+56|56)?\s?9\s?\d{4}\s?\d{4}$')
_RUT_PATTERN = re.compile(r'^\d{1,8}-[\dkK]$')

INVALID_PHONE_MSG = 'Número de teléfono chileno inválido. Formato: +56 9 XXXX XXXX'
INVALID_RUT_MSG = 'RUT inválido. Formato: 12345678-9 (incluir dígito verificador)'

# ── Validadores ───────────────────────────────────────────────────────────────


def validate_phone(phone: str) -> bool:
    """Retorna True si el teléfono tiene formato chileno válido (+56 9 XXXX XXXX)."""
    if not phone:
        return False
    cleaned = phone.replace(' ', '')
    return bool(_PHONE_PATTERN.match(cleaned))


def normalize_phone(phone: str) -> str:
    """Normaliza teléfono a formato +569XXXXXXXX (sin espacios)."""
    cleaned = phone.replace(' ', '')
    if cleaned.startswith('569'):
        return f'+{cleaned}'
    if cleaned.startswith('56'):
        return f'+{cleaned}'
    if cleaned.startswith('+56'):
        return cleaned
    # Asumir número local (9XXXXXXXX)
    if cleaned.startswith('9') and len(cleaned) == 9:
        return f'+56{cleaned}'
    return phone


def validate_rut(rut: str) -> bool:
    """
    Valida RUT chileno con módulo 11.
    Acepta tanto formato con puntos (12.345.678-9) como sin puntos (12345678-9).
    """
    if not rut:
        return False
    # Normalizar primero: quitar puntos y espacios, mayúsculas
    rut = rut.strip().replace('.', '').upper()
    if not _RUT_PATTERN.match(rut):
        return False

    body, dv = rut.split('-')
    try:
        return _compute_dv(int(body)) == dv
    except (ValueError, ZeroDivisionError):
        return False


def normalize_rut(rut: str) -> str:
    """Normaliza RUT a formato XXXXXXXX-D (sin puntos, con guion, DV en mayúscula)."""
    cleaned = rut.strip().replace('.', '').upper()
    return cleaned


def _compute_dv(rut_body: int) -> str:
    """Calcula el dígito verificador de un RUT usando módulo 11."""
    series = [2, 3, 4, 5, 6, 7]
    total = 0
    idx = 0
    n = rut_body
    while n > 0:
        total += (n % 10) * series[idx % 6]
        n //= 10
        idx += 1
    remainder = 11 - (total % 11)
    if remainder == 11:
        return '0'
    if remainder == 10:
        return 'K'
    return str(remainder)
