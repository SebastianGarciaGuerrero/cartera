"""
Configuración centralizada de la aplicación.
Lee las variables de entorno (o backend/.env en desarrollo).

Regla: en producción la app NO arranca con valores inseguros. Si falta la
SECRET_KEY o es la de ejemplo, falla al iniciar en vez de quedar expuesta.
"""

from typing import List, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CLAVE_DESARROLLO = "dev-secret-cambiar-en-produccion-por-favor"


class Settings(BaseSettings):
    # Base de datos (usuario dueño de las tablas; la app baja a ROL_APP en
    # cada transacción autenticada).
    database_url: str
    sql_echo: bool = False
    pool_size: int = 5
    pool_max_overflow: int = 10

    # Rol restringido con RLS. Vacío = no se baja de rol (solo para bases que
    # no permiten SET ROLE; el filtro por organización del ORM sigue activo).
    rol_app: str = "cartera_app"

    # General
    app_name: str = "Cartera API"
    environment: Literal["development", "test", "demo", "production"] = "development"
    debug: bool = False
    # URL pública del frontend (enlaces de los correos de recuperación).
    url_publica: str = "http://localhost:5173"
    # Hosts aceptados en el header Host. Vacío = cualquiera (desarrollo).
    hosts_permitidos: List[str] = []

    # Tokens. El access token es corto y vive solo en memoria del navegador;
    # el refresh token va en cookie httpOnly y se rota en cada uso.
    secret_key: str = CLAVE_DESARROLLO
    jwt_emisor: str = "cartera"
    jwt_audiencia: str = "cartera-app"
    access_token_minutos: int = 15
    sesion_inactividad_horas: int = 8
    sesion_maxima_dias: int = 7
    cookie_segura: bool = True

    # Cifrado de secretos en la base (semillas 2FA). Si no se define, se
    # deriva de secret_key.
    clave_cifrado: str = ""

    # Fuerza bruta: tras N intentos fallidos la cuenta se bloquea M minutos.
    login_max_intentos: int = 5
    login_bloqueo_minutos: int = 15
    # Límite por IP (ventana deslizante) para login y recuperación.
    limite_ip_intentos: int = 20
    limite_ip_ventana_segundos: int = 300

    # Correo saliente de la plataforma (recuperación de contraseña, avisos).
    # Con Google Workspace: smtp.gmail.com:587 + contraseña de aplicación.
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_password: str = ""
    smtp_remitente: str = ""

    # Subida de archivos
    max_archivo_mb: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("hosts_permitidos", mode="before")
    @classmethod
    def _lista_desde_texto(cls, v):
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        return v

    @model_validator(mode="after")
    def _validar_produccion(self):
        if self.environment in ("production", "demo"):
            if self.secret_key == CLAVE_DESARROLLO or len(self.secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY insegura: en producción debe ser un valor aleatorio "
                    "de al menos 32 caracteres (ej. `python -c \"import secrets; "
                    "print(secrets.token_urlsafe(48))\"`)."
                )
            if self.debug:
                raise ValueError("DEBUG debe ser false en producción.")
        if self.environment in ("development", "test"):
            # En localhost (http) el navegador descarta cookies Secure.
            self.cookie_segura = False
        return self

    @property
    def es_produccion(self) -> bool:
        return self.environment in ("production", "demo")


settings = Settings()
