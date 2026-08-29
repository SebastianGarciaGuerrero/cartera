"""
Configuración centralizada de la aplicación.
Lee las variables de entorno desde el archivo .env
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración tipada de la aplicación.
    Pydantic valida automáticamente los tipos al leer el .env
    """
    
    # Base de datos
    database_url: str
    
    # Configuración general
    app_name: str = "Cartera API"
    environment: str = "development"
    debug: bool = True

    # Seguridad / JWT
    # ⚠️ secret_key: en PRODUCCIÓN debe venir del .env con un valor largo y
    # aleatorio (ej. `openssl rand -hex 32`). Este default es SOLO para
    # desarrollo local. Si se filtra, cualquiera puede firmar tokens válidos.
    secret_key: str = "dev-secret-cambiar-en-produccion-por-favor"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 horas (una jornada laboral)
    
    # Configuración para leer el archivo .env
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Instancia única de configuración (singleton)
# Se importa desde cualquier parte del código con: from app.config import settings
settings = Settings()