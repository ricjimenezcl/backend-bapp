import re
from typing import Optional

def validate_chilean_rut(rut: str) -> bool:
    """Validar RUT chileno"""
    rut = rut.upper().replace(".", "").replace("-", "")
    
    if not re.match(r'^[0-9]+[0-9K]$', rut):
        return False
    
    body, dv = rut[:-1], rut[-1]
    
    # Calcular dígito verificador
    suma = 0
    multiplo = 2
    
    for i in range(len(body)-1, -1, -1):
        suma += int(body[i]) * multiplo
        multiplo = multiplo + 1 if multiplo < 7 else 2
    
    resto = suma % 11
    dv_calculado = 11 - resto
    if dv_calculado == 10:
        dv_calculado = 'K'
    elif dv_calculado == 11:
        dv_calculado = '0'
    
    return str(dv_calculado) == dv

def validate_chilean_phone(phone: str) -> bool:
    """Validar número de teléfono chileno"""
    # Formato: +56912345678 o 56912345678 o 912345678
    pattern = r'^(\+56|56)?\s?9\s?[0-9]{4}\s?[0-9]{4}$'
    phone_clean = re.sub(r'\s+', '', phone)
    return bool(re.match(pattern, phone_clean))

def validate_email(email: str) -> bool:
    """Validar formato de email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """Validar fortaleza de contraseña"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    return True, None

def format_chilean_phone(phone: str) -> str:
    """Formatear número de teléfono chileno"""
    phone_clean = re.sub(r'[^\d]', '', phone)
    
    if phone_clean.startswith('56'):
        phone_clean = phone_clean[2:]
    
    if not phone_clean.startswith('9'):
        phone_clean = '9' + phone_clean
    
    return f"+56{phone_clean}"