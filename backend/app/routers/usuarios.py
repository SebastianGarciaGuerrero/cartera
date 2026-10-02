"""
Gestión de usuarios de la organización — SOLO ADMIN.

No hay registro público: el admin de cada estudio crea las cuentas de su
equipo (y de sus mandantes para el portal), asigna roles y resuelve
bloqueos. Todo queda dentro de su organización (app/tenancy.py).

  GET  /api/usuarios                    → listar el equipo
  GET  /api/usuarios/roles              → catálogo de roles (para el select)
  GET  /api/usuarios/{id}               → obtener uno
  POST /api/usuarios                    → crear (invitación por correo o clave temporal)
  PUT  /api/usuarios/{id}               → editar (nombre, email, rol, activo)
  PUT  /api/usuarios/{id}/password      → fijar clave temporal (cierra sus sesiones)
  POST /api/usuarios/{id}/invitar       → reenviar invitación / enlace para elegir clave
  POST /api/usuarios/{id}/desbloquear   → quitar bloqueo por intentos fallidos
  POST /api/usuarios/{id}/reiniciar-2fa → quitar el 2FA (perdió el teléfono)

No hay DELETE: un usuario se desactiva (activo=False), se le cierran todas
las sesiones y su historial (gestiones, pagos que registró) queda intacto.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.correo import ErrorCorreo, enviar_correo
from app.database import get_db
from app.models.cliente import Cliente
from app.models.rol import Rol
from app.models.seguridad import TokenUnUso
from app.models.usuario import Usuario
from app.security import hashear_password, require_admin, validar_password
from app.sesiones import hash_token, nuevo_token, registrar_evento, revocar_todas
from app.tenancy import sesion_sistema
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse, PasswordReset


router = APIRouter(
    prefix="/api/usuarios",
    tags=["Usuarios (admin)"],
    dependencies=[Depends(require_admin)],
)

DURACION_INVITACION = timedelta(days=3)


class RolResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


def _obtener(db: Session, usuario_id: UUID) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail=f"Usuario con id {usuario_id} no encontrado")
    return usuario


def _validar_rol_y_cliente(db: Session, rol_id: int, cliente_id: Optional[UUID]) -> None:
    rol = db.get(Rol, rol_id)
    if rol is None:
        raise HTTPException(status_code=400, detail="Rol inexistente.")
    if rol.nombre == "mandante":
        if cliente_id is None or db.get(Cliente, cliente_id) is None:
            raise HTTPException(
                status_code=400,
                detail="Los usuarios del portal de clientes deben tener un cliente asignado.",
            )
    elif cliente_id is not None:
        raise HTTPException(status_code=400, detail="Solo el rol 'mandante' lleva cliente asignado.")


def _enviar_invitacion(usuario_id: UUID, email: str, nombre: str, admin: Usuario,
                       request: Request) -> bool:
    """Crea el enlace de un solo uso y lo envía. Devuelve si el correo salió."""
    token = nuevo_token()
    with sesion_sistema() as sdb:
        sdb.add(TokenUnUso(
            usuario_id=usuario_id,
            proposito="invitacion",
            token_hash=hash_token(token),
            expira_at=datetime.now(timezone.utc) + DURACION_INVITACION,
            ip=request.client.host if request.client else None,
        ))
        sdb.commit()
    enlace = f"{settings.url_publica.rstrip('/')}/restablecer?token={token}&bienvenida=1"
    org = request.state.organizacion
    try:
        enviar_correo(
            email,
            f"Te invitaron a {org.nombre} en Cartera",
            f"Hola {nombre}:\n\n{admin.nombre} te creó una cuenta en Cartera para {org.nombre}.\n"
            f"Entra a este enlace para elegir tu contraseña (vale 3 días, un solo uso):\n\n"
            f"{enlace}\n",
        )
        return True
    except ErrorCorreo:
        return False


@router.get("/roles", response_model=List[RolResponse])
def listar_roles(db: Session = Depends(get_db)):
    """Catálogo de roles."""
    return db.query(Rol).order_by(Rol.id).all()


@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(db: Session = Depends(get_db)):
    """Lista todo el equipo (activos e inactivos)."""
    return db.query(Usuario).order_by(Usuario.nombre).all()


@router.get("/{usuario_id}", response_model=UsuarioResponse)
def obtener_usuario(usuario_id: UUID, db: Session = Depends(get_db)):
    return _obtener(db, usuario_id)


@router.post("/", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    datos: UsuarioCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    _validar_rol_y_cliente(db, datos.rol_id, datos.cliente_id)
    if datos.password:
        try:
            validar_password(datos.password, datos.email)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        clave = hashear_password(datos.password)
    else:
        # Clave aleatoria que nadie conoce: entra con el enlace de invitación.
        clave = hashear_password(nuevo_token())

    nuevo = Usuario(
        nombre=datos.nombre,
        email=datos.email.lower(),
        password_hash=clave,
        rol_id=datos.rol_id,
        cliente_id=datos.cliente_id,
        debe_cambiar_password=bool(datos.password),
    )
    try:
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese email ya está registrado.")

    if not datos.password:
        enviado = _enviar_invitacion(nuevo.id, nuevo.email, nuevo.nombre, admin, request)
        response.headers["X-Invitacion-Enviada"] = "1" if enviado else "0"
    return nuevo


@router.put("/{usuario_id}", response_model=UsuarioResponse)
def actualizar_usuario(
    usuario_id: UUID,
    datos: UsuarioUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    usuario = _obtener(db, usuario_id)
    cambios = datos.model_dump(exclude_unset=True)

    if usuario.id == admin.id and (
        cambios.get("activo") is False or ("rol_id" in cambios and cambios["rol_id"] != usuario.rol_id)
    ):
        raise HTTPException(
            status_code=400,
            detail="No puedes desactivarte ni quitarte el rol de administrador a ti mismo.",
        )
    if "rol_id" in cambios or "cliente_id" in cambios:
        _validar_rol_y_cliente(db, cambios.get("rol_id", usuario.rol_id),
                               cambios.get("cliente_id", usuario.cliente_id))
    if "email" in cambios and cambios["email"]:
        cambios["email"] = cambios["email"].lower()

    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)

    try:
        db.commit()
        db.refresh(usuario)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese email ya está registrado.")

    if cambios.get("activo") is False or "rol_id" in cambios:
        # Desactivado o con otros permisos: sus sesiones abiertas se cierran.
        with sesion_sistema() as sdb:
            revocar_todas(sdb, usuario.id, "cambio_por_admin")
            sdb.commit()
    return usuario


@router.put("/{usuario_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def resetear_password(
    usuario_id: UUID,
    datos: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _obtener(db, usuario_id)
    try:
        validar_password(datos.password_nueva, usuario.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    usuario.password_hash = hashear_password(datos.password_nueva)
    usuario.password_actualizada_at = func.now()
    usuario.debe_cambiar_password = True
    db.commit()
    with sesion_sistema() as sdb:
        revocar_todas(sdb, usuario.id, "password_reseteada_por_admin")
        registrar_evento(sdb, "password_reseteada_por_admin", True, request=request,
                         usuario_id=usuario.id, organizacion_id=usuario.organizacion_id)
        sdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{usuario_id}/invitar", status_code=status.HTTP_202_ACCEPTED)
def reenviar_invitacion(
    usuario_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    usuario = _obtener(db, usuario_id)
    enviado = _enviar_invitacion(usuario.id, usuario.email, usuario.nombre, admin, request)
    if not enviado:
        raise HTTPException(status_code=503, detail="No se pudo enviar el correo. Revisa la configuración SMTP.")
    return {"mensaje": f"Se envió un enlace a {usuario.email}"}


@router.post("/{usuario_id}/desbloquear", status_code=status.HTTP_204_NO_CONTENT)
def desbloquear(usuario_id: UUID, db: Session = Depends(get_db)):
    usuario = _obtener(db, usuario_id)
    usuario.bloqueado_hasta = None
    usuario.intentos_fallidos = 0
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{usuario_id}/reiniciar-2fa", status_code=status.HTTP_204_NO_CONTENT)
def reiniciar_2fa(usuario_id: UUID, request: Request, db: Session = Depends(get_db)):
    usuario = _obtener(db, usuario_id)
    usuario.mfa_activo = False
    usuario.mfa_secreto_cifrado = None
    usuario.mfa_codigos_recuperacion = []
    db.commit()
    with sesion_sistema() as sdb:
        revocar_todas(sdb, usuario.id, "2fa_reiniciado_por_admin")
        registrar_evento(sdb, "mfa_reiniciado_por_admin", True, request=request,
                         usuario_id=usuario.id, organizacion_id=usuario.organizacion_id)
        sdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
