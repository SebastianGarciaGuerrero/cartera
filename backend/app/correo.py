"""
Envío de correos de la PLATAFORMA (recuperación de contraseña, avisos de
seguridad). Los correos de cobranza a deudores van por el módulo de
comunicaciones, con la cuenta de cada estudio.

Con Google Workspace: SMTP_HOST=smtp.gmail.com, SMTP_PUERTO=587, usuario =
la casilla y SMTP_PASSWORD = una "contraseña de aplicación" (no la clave
normal). Sin SMTP configurado, en desarrollo el correo se imprime en el log.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("cartera.correo")


class ErrorCorreo(RuntimeError):
    pass


def correo_configurado() -> bool:
    return bool(settings.smtp_host and settings.smtp_remitente)


def enviar_correo(destinatario: str, asunto: str, texto: str, html: str | None = None) -> None:
    if not correo_configurado():
        if settings.es_produccion:
            raise ErrorCorreo("El correo saliente no está configurado (SMTP_HOST).")
        log.warning("Correo NO enviado (SMTP sin configurar) a %s: %s\n%s",
                    destinatario, asunto, texto)
        return

    msg = EmailMessage()
    msg["From"] = settings.smtp_remitente
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")

    contexto = ssl.create_default_context()
    try:
        if settings.smtp_puerto == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_puerto,
                                  context=contexto, timeout=15) as s:
                _login_y_enviar(s, msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_puerto, timeout=15) as s:
                s.starttls(context=contexto)
                _login_y_enviar(s, msg)
    except (smtplib.SMTPException, OSError) as e:
        log.error("Fallo SMTP al enviar a %s: %s", destinatario, e)
        raise ErrorCorreo("No se pudo enviar el correo.") from e


def _login_y_enviar(servidor, msg) -> None:
    if settings.smtp_usuario:
        servidor.login(settings.smtp_usuario, settings.smtp_password)
    servidor.send_message(msg)
