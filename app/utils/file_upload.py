import os
import uuid
from fastapi import UploadFile, HTTPException
from typing import List
import aiofiles

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

async def save_uploaded_file(file: UploadFile, upload_dir: str = "uploads") -> str:
    """Guardar archivo subido y retornar la ruta"""
    
    # Validar extensión
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {file_extension} not allowed")
    
    # Crear directorio si no existe
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generar nombre único
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    # Guardar archivo
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        
        # Validar tamaño
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(400, "File too large")
        
        await f.write(content)
    
    return file_path

async def save_multiple_files(files: List[UploadFile], upload_dir: str = "uploads") -> List[str]:
    """Guardar múltiples archivos"""
    file_paths = []
    
    for file in files:
        file_path = await save_uploaded_file(file, upload_dir)
        file_paths.append(file_path)
    
    return file_paths

def validate_file_type(file: UploadFile) -> bool:
    """Validar tipo de archivo"""
    file_extension = os.path.splitext(file.filename)[1].lower()
    return file_extension in ALLOWED_EXTENSIONS

def get_file_extension(filename: str) -> str:
    """Obtener extensión del archivo"""
    return os.path.splitext(filename)[1].lower()