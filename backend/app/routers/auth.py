"""
Autenticación y cuenta propia.

  POST /api/auth/login              email + contraseña → token (o pide 2FA)
  POST /api/auth/login/mfa          completa el login con el código 2FA
  POST /api/auth/refresh            cookie de refresh → token nuevo (rota la cookie)
  POST /api/auth/logout             cierra la sesión actual
  GET  /api/auth/me                 usuario, organización, plan y funciones
  PUT  /api/auth/cambiar-password   cambia la propia (cierra las otras sesiones)
  POST /api/auth/recuperar          envía enlace de recuperación por correo
  POST /api/auth/restablecer        fija contraseña nueva con el enlace
  POST /api/auth/mfa/iniciar        genera QR para activar 2FA
  POST /api/auth/mfa/confirmar      activa 2FA (devuelve códigos de recuperación)
  POST /api/auth/mfa/desactivar     desactiva 2FA (pide contraseña + código)
  GET  /api/auth/sesiones           mis sesiones abiertas
  DELETE /api/auth/sesiones/{id}    cerrar una sesión (ej. un PC olvidado)

Reglas: mensajes de error genéricos (no revelan si un email existe), tiempo
de respuesta constante, bloqueo de cuenta tras intentos fallidos, límite por
IP y registro de cada evento en eventos_acceso.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import mfa
from app.auditoria import CLAVE_CONTEXTO
from app.config import settings
from app.correo import ErrorCorreo, enviar_correo
from app.database import get_db
from app.models.organizacion import Organizacion
from app.models.seguridad import Sesion, TokenUnUso
from app.models.usuario import Usuario
from app.planes import funciones_de
from app.schemas.auth import (
    CambiarPassword, CodigosRecuperacion, LoginEntrada, MfaConfirmar, MfaDesactivar,
    MfaEntrada, MfaInicio, MfaPendiente, OrganizacionActual, RecuperarEntrada,
    RestablecerEntrada, SesionActiva, TokenRespuesta, UsuarioActual,
)
from app.security import (
    crear_access_token, crear_token_mfa_pendiente, decodificar_token, get_current_user,
    hashear_password, ip_cliente, tiempo_constante_sin_usuario, validar_password,
    verificar_password,
)
from app.sesiones import (
    COOKIE_REFRESH, borrar_cookie_refresh, controlar_limite_ip, crear_sesion,
    exigir_cabecera_csrf, hash_token, nuevo_token, poner_cookie_refresh,
    registrar_evento, revocar, revocar_todas, rotar_sesion,
)
from app.tenancy import modo_sistema, sesion_sistema

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

CREDENCIALES_INVALIDAS = "Email o contraseña incorrectos"
DURACION_TOKEN_RESET = timedelta(minutes=30)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _usuario_actual(usuario: Usuario, org: Organizacion) -> UsuarioActual:
    return UsuarioActual(
        id=usuario.id,
        nombre=usuario.nombre,
        email=usuario.email,
        rol_id=usuario.rol_id,
        rol=usuario.rol_nombre or "",
        cliente_id=usuario.cliente_id,
        mfa_activo=usuario.mfa_activo,
        debe_cambiar_password=usuario.debe_cambiar_password,
        organizacion=OrganizacionActual(
            id=org.id,
            nombre=org.nombre,
            plan=org.plan,
            estado=org.estado,
            funciones=sorted(funciones_de(org)),
            etiquetas=(org.configuracion or {}).get("etiquetas") or {},
        ),
    )


def _buscar_por_email(db: Session, email: str) -> Usuario | None:
    return db.query(Usuario).filter(func.lower(Usuario.email) == email.lower()).first()


def _registrar_fallo(db: Session, usuario: Usuario) -> None:
    usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
    if usuario.intentos_fallidos >= settings.login_max_intentos:
        usuario.bloqueado_hasta = _ahora() + timedelta(minutes=settings.login_bloqueo_minutos)
        usuario.intentos_fallidos = 0


def _verificar_bloqueo(usuario: Usuario) -> None:
    if usuario.bloqueado_hasta and usuario.bloqueado_hasta > _ahora():
        minutos = int((usuario.bloqueado_hasta - _ahora()).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Intenta de nuevo en {minutos} minuto(s) "
                   "o recupera tu contraseña.",
        )


def _emitir_sesion(db: Session, usuario: Usuario, org: Organizacion,
                   request: Request, response: Response) -> TokenRespuesta:
    """Login exitoso: crea la sesión, pone la cookie y devuelve el token."""
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_acceso = _ahora()
    sesion, refresh = crear_sesion(db, usuario, request)
    registrar_evento(db, "login", True, request=request, usuario_id=usuario.id,
                     organizacion_id=usuario.organizacion_id, email=usuario.email)
    db.commit()
    poner_cookie_refresh(response, refresh)
    return TokenRespuesta(
        access_token=crear_access_token(usuario, sesion.id),
        expira_en=settings.access_token_minutos * 60,
        usuario=_usuario_actual(usuario, org),
    )


@router.post("/login", response_model=Union[TokenRespuesta, MfaPendiente])
def login(datos: LoginEntrada, request: Request, response: Response,
          db: Session = Depends(get_db)):
    controlar_limite_ip(request, "login")
    modo_sistema(db)
    db.info[CLAVE_CONTEXTO] = {"usuario_id": None, "ip": ip_cliente(request)}

    usuario = _buscar_por_email(db, datos.email)
    if usuario is None:
        tiempo_constante_sin_usuario(datos.password)
        registrar_evento(db, "login", False, request=request, email=datos.email,
                         detalle={"motivo": "email_desconocido"})
        db.commit()
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    db.info[CLAVE_CONTEXTO]["usuario_id"] = usuario.id
    _verificar_bloqueo(usuario)

    ok, rehash = verificar_password(datos.password, usuario.password_hash)
    if not ok or not usuario.activo:
        if not ok:
            _registrar_fallo(db, usuario)
        registrar_evento(db, "login", False, request=request, usuario_id=usuario.id,
                         organizacion_id=usuario.organizacion_id, email=datos.email,
                         detalle={"motivo": "password" if not ok else "inactivo"})
        db.commit()
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    if rehash:
        usuario.password_hash = hashear_password(datos.password)

    org = db.get(Organizacion, usuario.organizacion_id)
    if org is None or not org.habilitada:
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="La cuenta de tu organización está suspendida. Contacta a soporte.",
        )

    if usuario.mfa_activo:
        registrar_evento(db, "login_password_ok", True, request=request, usuario_id=usuario.id,
                         organizacion_id=usuario.organizacion_id, email=usuario.email)
        db.commit()
        return MfaPendiente(mfa_token=crear_token_mfa_pendiente(usuario))

    return _emitir_sesion(db, usuario, org, request, response)


@router.post("/login/mfa", response_model=TokenRespuesta)
def login_mfa(datos: MfaEntrada, request: Request, response: Response,
              db: Session = Depends(get_db)):
    controlar_limite_ip(request, "login")
    modo_sistema(db)
    try:
        claims = decodificar_token(datos.mfa_token, "mfa")
        usuario = db.get(Usuario, UUID(claims["sub"]))
    except (ValueError, KeyError):
        usuario = None
    if usuario is None or not usuario.activo or not usuario.mfa_activo:
        raise HTTPException(status_code=401, detail="El inicio de sesión venció. Vuelve a empezar.")
    db.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
    _verificar_bloqueo(usuario)

    codigo = datos.codigo.strip()
    valido = mfa.verificar_codigo(usuario, codigo)
    usado_recuperacion = False
    if not valido and len(codigo) > 6:
        valido = usado_recuperacion = mfa.usar_codigo_recuperacion(usuario, codigo)
    if not valido:
        _registrar_fallo(db, usuario)
        registrar_evento(db, "login_mfa", False, request=request, usuario_id=usuario.id,
                         organizacion_id=usuario.organizacion_id, email=usuario.email)
        db.commit()
        raise HTTPException(status_code=401, detail="Código incorrecto.")

    if usado_recuperacion:
        registrar_evento(db, "mfa_codigo_recuperacion_usado", True, request=request,
                         usuario_id=usuario.id, organizacion_id=usuario.organizacion_id,
                         detalle={"restantes": len(usuario.mfa_codigos_recuperacion)})

    org = db.get(Organizacion, usuario.organizacion_id)
    if org is None or not org.habilitada:
        raise HTTPException(status_code=403, detail="La cuenta de tu organización está suspendida.")
    return _emitir_sesion(db, usuario, org, request, response)


@router.post("/refresh", response_model=TokenRespuesta)
def refrescar(request: Request, response: Response, db: Session = Depends(get_db)):
    exigir_cabecera_csrf(request)
    token = request.cookies.get(COOKIE_REFRESH)
    if not token:
        raise HTTPException(status_code=401, detail="Sin sesión.")
    modo_sistema(db)
    try:
        sesion, nuevo = rotar_sesion(db, token)
    except HTTPException:
        borrar_cookie_refresh(response)
        raise
    usuario = db.get(Usuario, sesion.usuario_id)
    org = db.get(Organizacion, sesion.organizacion_id)
    if usuario is None or not usuario.activo or org is None or not org.habilitada:
        revocar(db, sesion, "cuenta_deshabilitada")
        db.commit()
        borrar_cookie_refresh(response)
        raise HTTPException(status_code=401, detail="Sesión no válida.")
    db.commit()
    if nuevo:
        poner_cookie_refresh(response, nuevo)
    return TokenRespuesta(
        access_token=crear_access_token(usuario, sesion.id),
        expira_en=settings.access_token_minutos * 60,
        usuario=_usuario_actual(usuario, org),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    exigir_cabecera_csrf(request)
    token = request.cookies.get(COOKIE_REFRESH)
    if token:
        modo_sistema(db)
        sesion = db.query(Sesion).filter(Sesion.refresh_hash == hash_token(token)).first()
        if sesion is not None:
            revocar(db, sesion, "logout")
            registrar_evento(db, "logout", True, request=request, usuario_id=sesion.usuario_id,
                             organizacion_id=sesion.organizacion_id)
            db.commit()
    borrar_cookie_refresh(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UsuarioActual)
def yo(request: Request, usuario: Usuario = Depends(get_current_user)):
    return _usuario_actual(usuario, request.state.organizacion)


@router.put("/cambiar-password", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_mi_password(datos: CambiarPassword, request: Request,
                        usuario: Usuario = Depends(get_current_user)):
    try:
        validar_password(datos.password_nueva, usuario.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    sid = _sid_actual(request)
    with sesion_sistema() as sdb:
        sdb.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
        u = sdb.get(Usuario, usuario.id)
        ok, _ = verificar_password(datos.password_actual, u.password_hash)
        if not ok:
            registrar_evento(sdb, "cambio_password", False, request=request, usuario_id=u.id,
                             organizacion_id=u.organizacion_id)
            sdb.commit()
            raise HTTPException(status_code=401, detail="La contraseña actual no es correcta")
        u.password_hash = hashear_password(datos.password_nueva)
        u.password_actualizada_at = _ahora()
        u.debe_cambiar_password = False
        revocar_todas(sdb, u.id, "cambio_password", excepto=sid)
        registrar_evento(sdb, "cambio_password", True, request=request, usuario_id=u.id,
                         organizacion_id=u.organizacion_id)
        sdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sid_actual(request: Request):
    auth = request.headers.get("authorization", "")
    try:
        return UUID(decodificar_token(auth.split(" ", 1)[1], "access")["sid"])
    except (ValueError, KeyError, IndexError):
        return None


@router.post("/recuperar", status_code=status.HTTP_202_ACCEPTED)
def recuperar_password(datos: RecuperarEntrada, request: Request,
                       db: Session = Depends(get_db)):
    """Siempre responde 202 (no revela si el email existe)."""
    controlar_limite_ip(request, "recuperar")
    modo_sistema(db)
    usuario = _buscar_por_email(db, datos.email)
    if usuario is None or not usuario.activo:
        registrar_evento(db, "recuperar_password", False, request=request, email=datos.email)
        db.commit()
        return {"mensaje": "Si el email está registrado, te enviamos un enlace."}

    token = nuevo_token()
    db.add(TokenUnUso(
        usuario_id=usuario.id,
        proposito="reset_password",
        token_hash=hash_token(token),
        expira_at=_ahora() + DURACION_TOKEN_RESET,
        ip=ip_cliente(request),
    ))
    registrar_evento(db, "recuperar_password", True, request=request, usuario_id=usuario.id,
                     organizacion_id=usuario.organizacion_id, email=usuario.email)
    db.commit()

    enlace = f"{settings.url_publica.rstrip('/')}/restablecer?token={token}"
    try:
        enviar_correo(
            usuario.email,
            "Recupera tu contraseña",
            f"Hola {usuario.nombre}:\n\nPara elegir una contraseña nueva entra a este enlace "
            f"(vale por 30 minutos y sirve una sola vez):\n\n{enlace}\n\n"
            "Si no lo pediste tú, ignora este correo: tu contraseña no cambia.",
        )
    except ErrorCorreo:
        pass  # el usuario ve la misma respuesta; el error queda en el log
    return {"mensaje": "Si el email está registrado, te enviamos un enlace."}


@router.post("/restablecer", status_code=status.HTTP_204_NO_CONTENT)
def restablecer_password(datos: RestablecerEntrada, request: Request,
                         db: Session = Depends(get_db)):
    controlar_limite_ip(request, "recuperar")
    modo_sistema(db)
    registro = (
        db.query(TokenUnUso)
        .filter(TokenUnUso.token_hash == hash_token(datos.token),
                TokenUnUso.proposito.in_(("reset_password", "invitacion")))
        .with_for_update().first()
    )
    if registro is None or registro.usado_at is not None or registro.expira_at <= _ahora():
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya venció. Pide uno nuevo.")
    usuario = db.get(Usuario, registro.usuario_id)
    try:
        validar_password(datos.password_nueva, usuario.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
    registro.usado_at = _ahora()
    usuario.password_hash = hashear_password(datos.password_nueva)
    usuario.password_actualizada_at = _ahora()
    usuario.debe_cambiar_password = False
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    revocar_todas(db, usuario.id, "restablecer_password")
    registrar_evento(db, "restablecer_password", True, request=request, usuario_id=usuario.id,
                     organizacion_id=usuario.organizacion_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 2FA
# ============================================================

@router.post("/mfa/iniciar", response_model=MfaInicio)
def mfa_iniciar(request: Request, usuario: Usuario = Depends(get_current_user)):
    if usuario.mfa_activo:
        raise HTTPException(status_code=400, detail="El 2FA ya está activo.")
    semilla = mfa.nueva_semilla()
    with sesion_sistema() as sdb:
        u = sdb.get(Usuario, usuario.id)
        u.mfa_secreto_cifrado = mfa.cifrar(semilla)
        u.mfa_ultimo_paso = None
        sdb.commit()
    uri = mfa.uri_configuracion(semilla, usuario.email)
    return MfaInicio(qr=mfa.qr_svg(uri), secreto=semilla, uri=uri)


@router.post("/mfa/confirmar", response_model=CodigosRecuperacion)
def mfa_confirmar(datos: MfaConfirmar, request: Request,
                  usuario: Usuario = Depends(get_current_user)):
    with sesion_sistema() as sdb:
        sdb.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
        u = sdb.get(Usuario, usuario.id)
        if u.mfa_activo or not u.mfa_secreto_cifrado:
            raise HTTPException(status_code=400, detail="Primero genera el código QR.")
        if not mfa.verificar_codigo(u, datos.codigo):
            raise HTTPException(status_code=400, detail="Código incorrecto. Revisa la hora del teléfono.")
        codigos, hashes = mfa.generar_codigos_recuperacion()
        u.mfa_activo = True
        u.mfa_codigos_recuperacion = hashes
        registrar_evento(sdb, "mfa_activado", True, request=request, usuario_id=u.id,
                         organizacion_id=u.organizacion_id)
        sdb.commit()
    return CodigosRecuperacion(codigos=codigos)


@router.post("/mfa/desactivar", status_code=status.HTTP_204_NO_CONTENT)
def mfa_desactivar(datos: MfaDesactivar, request: Request,
                   usuario: Usuario = Depends(get_current_user)):
    with sesion_sistema() as sdb:
        sdb.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
        u = sdb.get(Usuario, usuario.id)
        ok, _ = verificar_password(datos.password, u.password_hash)
        codigo_ok = mfa.verificar_codigo(u, datos.codigo) or mfa.usar_codigo_recuperacion(u, datos.codigo)
        if not (ok and codigo_ok and u.mfa_activo):
            registrar_evento(sdb, "mfa_desactivado", False, request=request, usuario_id=u.id,
                             organizacion_id=u.organizacion_id)
            sdb.commit()
            raise HTTPException(status_code=400, detail="Contraseña o código incorrecto.")
        u.mfa_activo = False
        u.mfa_secreto_cifrado = None
        u.mfa_codigos_recuperacion = []
        registrar_evento(sdb, "mfa_desactivado", True, request=request, usuario_id=u.id,
                         organizacion_id=u.organizacion_id)
        sdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# Sesiones abiertas
# ============================================================

@router.get("/sesiones", response_model=List[SesionActiva])
def mis_sesiones(request: Request, usuario: Usuario = Depends(get_current_user)):
    sid = _sid_actual(request)
    with sesion_sistema() as sdb:
        sesiones = (
            sdb.query(Sesion)
            .filter(Sesion.usuario_id == usuario.id, Sesion.revocada_at.is_(None),
                    Sesion.expira_at > _ahora())
            .order_by(Sesion.ultimo_uso_at.desc()).all()
        )
        return [
            SesionActiva(id=s.id, creada_at=s.creada_at, ultimo_uso_at=s.ultimo_uso_at,
                         ip=s.ip, user_agent=s.user_agent, actual=(s.id == sid))
            for s in sesiones
        ]


@router.delete("/sesiones/{sesion_id}", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_sesion(sesion_id: UUID, request: Request,
                  usuario: Usuario = Depends(get_current_user)):
    with sesion_sistema() as sdb:
        sesion = sdb.get(Sesion, sesion_id)
        if sesion is None or sesion.usuario_id != usuario.id:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        revocar(sdb, sesion, "cerrada_por_usuario")
        sdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
