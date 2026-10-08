"""
Comandos de administración de la PLATAFORMA (los usa quien opera el SaaS,
no los estudios).

Desde la carpeta backend, con el venv activo:

  python -m app.cli crear-organizacion --nombre "Estudio Pérez" --slug perez \\
         --admin-nombre "Ana Pérez" --admin-email ana@perez.cl [--plan profesional]
      Crea la organización, sus datos de empresa y su administrador. Imprime
      un enlace (válido 3 días) para que el admin elija su contraseña.

  python -m app.cli listar-organizaciones
  python -m app.cli cambiar-plan --slug perez --plan premium
  python -m app.cli cambiar-estado --slug perez --estado suspendida
  python -m app.cli enlace-acceso --email ana@perez.cl
      Nuevo enlace para elegir contraseña (si se le perdió la invitación).

  python -m app.cli subir-logo --slug perez --archivo ../logos/perez.png
      Carga el logo que mandó la empresa (PNG o JPG, máx. 1 MB). Registrarlo
      también en logos/README.md.

  python -m app.cli enviar-agenda [--simular]
      Correo de la mañana a cada persona con su agenda del día (contactos,
      promesas, cuotas y recordatorios, más lo atrasado). Solo para las
      organizaciones con la función "recordatorios". Programarlo una vez al
      día (ej. 7:30) en el hosting (cron) o con el Programador de tareas.
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func

import app.models  # noqa: F401  (registra todos los modelos)
from app.config import settings
from app.models.empresa import Empresa
from app.models.organizacion import Organizacion
from app.models.rol import Rol
from app.models.seguridad import TokenUnUso
from app.models.usuario import Usuario
from app.security import hashear_password
from app.sesiones import hash_token, nuevo_token
from app.tenancy import sesion_sistema


def _enlace(db, usuario: Usuario) -> str:
    token = nuevo_token()
    db.add(TokenUnUso(
        usuario_id=usuario.id,
        proposito="invitacion",
        token_hash=hash_token(token),
        expira_at=datetime.now(timezone.utc) + timedelta(days=3),
    ))
    return f"{settings.url_publica.rstrip('/')}/restablecer?token={token}&bienvenida=1"


def crear_organizacion(args) -> None:
    try:
        validate_email(args.admin_email, check_deliverability=False)
    except EmailNotValidError as e:
        sys.exit(f"Email inválido: {e}")
    with sesion_sistema() as db:
        if db.query(Organizacion).filter(Organizacion.slug == args.slug).first():
            sys.exit(f"Ya existe una organización con slug '{args.slug}'.")
        if db.query(Usuario).filter(func.lower(Usuario.email) == args.admin_email.lower()).first():
            sys.exit(f"El email {args.admin_email} ya está registrado.")

        org = Organizacion(
            nombre=args.nombre,
            slug=args.slug,
            plan=args.plan,
            estado="prueba" if args.dias_prueba else "activa",
            prueba_hasta=(date.today() + timedelta(days=args.dias_prueba)) if args.dias_prueba else None,
            numero_cobranza_siguiente=args.numero_inicial,
        )
        db.add(org)
        db.flush()
        db.add(Empresa(
            organizacion_id=org.id,
            razon_social=args.nombre,
            nombre_fantasia=args.nombre,
            wordmark=args.nombre.upper(),
            firma_documentos=args.nombre,
        ))
        rol_admin = db.query(Rol).filter(Rol.nombre == "admin").one()
        admin = Usuario(
            organizacion_id=org.id,
            nombre=args.admin_nombre,
            email=args.admin_email.lower(),
            password_hash=hashear_password(nuevo_token()),  # nadie la conoce
            rol_id=rol_admin.id,
        )
        db.add(admin)
        db.flush()
        enlace = _enlace(db, admin)
        db.commit()
        print(f"Organización creada: {org.nombre} (slug {org.slug}, plan {org.plan}, id {org.id})")
        print(f"Administrador: {admin.email}")
        print(f"Enlace para elegir contraseña (3 días, un solo uso):\n  {enlace}")


def listar(args) -> None:
    with sesion_sistema() as db:
        for org in db.query(Organizacion).order_by(Organizacion.created_at).all():
            usuarios = db.query(Usuario).filter(Usuario.organizacion_id == org.id).count()
            print(f"{org.slug:<20} {org.plan:<12} {org.estado:<11} usuarios={usuarios:<4} {org.nombre}")


def cambiar(args, campo: str, valor: str) -> None:
    with sesion_sistema() as db:
        org = db.query(Organizacion).filter(Organizacion.slug == args.slug).first()
        if org is None:
            sys.exit(f"No existe la organización '{args.slug}'.")
        setattr(org, campo, valor)
        db.commit()
        print(f"{org.slug}: {campo} = {valor}")


def enviar_agenda(args) -> None:
    from app.agenda import items_agenda
    from app.correo import ErrorCorreo, enviar_correo
    from app.database import SessionLocal
    from app.indicadores import hoy_chile
    from app.planes import funciones_de
    from app.security import ROLES_INTERNOS
    from app.tenancy import activar_organizacion

    hoy = hoy_chile()
    with sesion_sistema() as db:
        orgs = [(o.id, o.nombre) for o in db.query(Organizacion).all()
                if o.habilitada and "recordatorios" in funciones_de(o)]
    enviados = 0
    for org_id, org_nombre in orgs:
        with sesion_sistema() as db:
            personas = [
                (u.id, u.nombre, u.email) for u in
                db.query(Usuario).filter(Usuario.organizacion_id == org_id, Usuario.activo.is_(True)).all()
                if u.rol_nombre in ROLES_INTERNOS
            ]
        for usuario_id, nombre, email in personas:
            db = SessionLocal()
            try:
                activar_organizacion(db, org_id)
                items = items_agenda(db, org_id, hoy - timedelta(days=60), hoy, usuario_id, hoy)
            finally:
                db.close()
            if not items:
                continue
            atrasados = [i for i in items if i.atrasado]
            de_hoy = [i for i in items if not i.atrasado]
            lineas = [f"Hola {nombre.split()[0]}, esta es tu agenda de hoy en {org_nombre}:", ""]
            for titulo, grupo in (("HOY", de_hoy), ("ATRASADO", atrasados)):
                if grupo:
                    lineas.append(f"{titulo} ({len(grupo)})")
                    for i in grupo:
                        cuando = "" if not i.atrasado else f" [{i.fecha.strftime('%d-%m')}]"
                        numero = f" (N° {i.numero_cobranza})" if i.numero_cobranza else ""
                        lineas.append(f"  - {i.titulo}{numero}{cuando}")
                    lineas.append("")
            lineas.append(f"Ver en Cartera: {settings.url_publica.rstrip('/')}/agenda")
            asunto = f"Tu agenda de hoy: {len(de_hoy)} pendiente(s)" + (
                f", {len(atrasados)} atrasado(s)" if atrasados else "")
            if args.simular:
                print(f"--- {email}: {asunto}")
                print("\n".join(lineas))
                continue
            try:
                enviar_correo(email, asunto, "\n".join(lineas))
                enviados += 1
            except ErrorCorreo as e:
                print(f"No se pudo enviar a {email}: {e}")
    print(f"Agendas enviadas: {enviados}")


def subir_logo(args) -> None:
    from pathlib import Path
    from app.logos import ErrorLogo, validar_logo
    from app.tenancy import activar_organizacion
    from app.database import SessionLocal

    archivo = Path(args.archivo)
    if not archivo.is_file():
        sys.exit(f"No existe el archivo {archivo}")
    datos = archivo.read_bytes()
    try:
        tipo = validar_logo(datos)
    except ErrorLogo as e:
        sys.exit(str(e))
    with sesion_sistema() as db:
        org = db.query(Organizacion).filter(Organizacion.slug == args.slug).first()
        if org is None:
            sys.exit(f"No existe la organización '{args.slug}'.")
        org_id = org.id
    db = SessionLocal()
    try:
        activar_organizacion(db, org_id)
        empresa = db.query(Empresa).first()
        if empresa is None:
            sys.exit("La organización no tiene datos de empresa cargados.")
        empresa.logo, empresa.logo_tipo = datos, tipo
        empresa.logo_actualizado_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    print(f"Logo cargado para {args.slug} ({tipo}, {len(datos) // 1024} KB).")


def enlace_acceso(args) -> None:
    with sesion_sistema() as db:
        usuario = db.query(Usuario).filter(func.lower(Usuario.email) == args.email.lower()).first()
        if usuario is None:
            sys.exit("No existe ese usuario.")
        enlace = _enlace(db, usuario)
        db.commit()
        print(enlace)


def main(argv=None) -> None:
    # Consolas de Windows con codificación antigua: que una tilde no corte el
    # comando a la mitad (el resto del texto se imprime igual).
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="python -m app.cli", description="Administración de la plataforma")
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("crear-organizacion")
    c.add_argument("--nombre", required=True)
    c.add_argument("--slug", required=True, help="identificador corto: minúsculas, números y guiones")
    c.add_argument("--admin-nombre", required=True)
    c.add_argument("--admin-email", required=True)
    c.add_argument("--plan", default="base", choices=["base", "profesional", "premium"])
    c.add_argument("--dias-prueba", type=int, default=0)
    c.add_argument("--numero-inicial", type=int, default=1000,
                   help="primer N° de cobranza (para no chocar con el sistema anterior)")
    c.set_defaults(func=crear_organizacion)

    sub.add_parser("listar-organizaciones").set_defaults(func=listar)

    c = sub.add_parser("cambiar-plan")
    c.add_argument("--slug", required=True)
    c.add_argument("--plan", required=True, choices=["base", "profesional", "premium"])
    c.set_defaults(func=lambda a: cambiar(a, "plan", a.plan))

    c = sub.add_parser("cambiar-estado")
    c.add_argument("--slug", required=True)
    c.add_argument("--estado", required=True, choices=["prueba", "activa", "suspendida", "cancelada"])
    c.set_defaults(func=lambda a: cambiar(a, "estado", a.estado))

    c = sub.add_parser("subir-logo")
    c.add_argument("--slug", required=True)
    c.add_argument("--archivo", required=True, help="PNG o JPG de hasta 1 MB")
    c.set_defaults(func=subir_logo)

    c = sub.add_parser("enviar-agenda")
    c.add_argument("--simular", action="store_true", help="muestra los correos sin enviarlos")
    c.set_defaults(func=enviar_agenda)

    c = sub.add_parser("enlace-acceso")
    c.add_argument("--email", required=True)
    c.set_defaults(func=enlace_acceso)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
