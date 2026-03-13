# app/core/config.py
from pydantic_settings import BaseSettings
from typing import List, Optional
from pydantic import Field
from pathlib import Path
import json

# Ruta absoluta al .env del backend (backend/.env)
# Funciona sin importar desde qué directorio se lanza el proceso
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(default="mysql+aiomysql://user:password@localhost/service_finder")
    DB_HOST: str = Field(default="localhost")
    DB_NAME: str = Field(default="service_finder")
    DB_USER: str = Field(default="user")
    DB_PASS: str = Field(default="password")
    DB_PORT: str = Field(default="3306")

    # Authentication
    SECRET_KEY: str = Field(default="your-secret-key-here-change-in-production")
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)

    # OAuth (optional for development)
    OAUTH_FB_CLIENT_ID: Optional[str] = Field(default=None)
    OAUTH_FB_CLIENT_SECRET: Optional[str] = Field(default=None)
    OAUTH_GOOGLE_CLIENT_ID: Optional[str] = Field(default=None)
    OAUTH_GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None)

    # External APIs (optional for development)
    GEOAPIFY_API_KEY: Optional[str] = Field(default=None)
    MERCADO_PAGO_ACCESS_TOKEN: Optional[str] = Field(default=None)
    TRANSBANK_API_KEY: Optional[str] = Field(default=None)
    SII_API_KEY: Optional[str] = Field(default=None)
    SII_SECRET_KEY: Optional[str] = Field(default=None)

    # Firebase (optional for development)
    FCM_SERVER_KEY: Optional[str] = Field(default=None)
    
    # Cloudinary Storage
    CLOUDINARY_CLOUD_NAME: Optional[str] = Field(default=None)
    CLOUDINARY_API_KEY: Optional[str] = Field(default=None)
    CLOUDINARY_API_SECRET: Optional[str] = Field(default=None)
    CLOUDINARY_UPLOAD_PRESET: str = Field(default="ml_default")

    # Twilio
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None)
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None)
    TWILIO_PHONE_NUMBER: Optional[str] = Field(default=None)
    TWILIO_WHATSAPP_NUMBER: Optional[str] = Field(default=None)

    # Resend Email Service
    RESEND_API_KEY: Optional[str] = Field(default=None)
    RESEND_FROM_EMAIL: str = Field(default="noreply@bappsearch.com")
    
    # AWS Rekognition - Face verification
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None)
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None)
    AWS_REGION: str = Field(default="us-east-1")
    
    # Redis Infrastructure
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    REDIS_PASSWORD: Optional[str] = Field(default=None)
    REDIS_URL: Optional[str] = Field(default=None)  # For production (Render)
    
    # Upstash Redis
    UPSTASH_REDIS_REST_URL: Optional[str] = Field(default=None)
    UPSTASH_REDIS_REST_TOKEN: Optional[str] = Field(default=None)
    REDIS_ENABLED: bool = Field(default=True)

    # PostGIS — Geolocalización avanzada
    # False = Haversine SQL (cualquier PostgreSQL, sin extensión)
    # True  = ST_DWithin + GiST (requiere migrations/003_postgis_geolocation.sql)
    USE_POSTGIS: bool = Field(default=False)

    # CORS - Maneja tanto string JSON como lista
    ALLOWED_ORIGINS: List[str] = Field(default=[
        "http://localhost:8100",
        "http://localhost:8000",
        "http://localhost:4200",
        "http://localhost:4201",
        "http://localhost:54805",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:4201"
    ])

    class Config:
        env_file = str(_ENV_FILE)
        case_sensitive = False
        extra = "ignore"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Si ALLOWED_ORIGINS viene como string JSON, conviértelo a lista
        if isinstance(self.ALLOWED_ORIGINS, str):
            try:
                self.ALLOWED_ORIGINS = json.loads(self.ALLOWED_ORIGINS)
            except json.JSONDecodeError:
                # Si no es JSON válido, asume que es una string separada por comas
                self.ALLOWED_ORIGINS = [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

settings = Settings()