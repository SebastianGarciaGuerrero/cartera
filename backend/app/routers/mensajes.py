"""
Mensaje de pago listo para enviar (plan base: función `mensaje_pago`).

  GET /api/cobranzas/{id}/mensaje-pago → texto con el saldo y los datos de
      transferencia, más los enlaces para abrirlo en WhatsApp o en el correo
      con el número / email del deudor ya puestos.

No envía nada por sí mismo: la persona revisa el texto, lo manda desde su
WhatsApp o su correo, y registra la gestión. (El envío automático es otra
función, del plan premium.)

La plantilla la define cada organización (Configuración → Cobro) con
marcadores entre llaves: {deudor}, {nombre}, {saldo}, {numero}, {id_externo},
{cliente}, {empresa}, {datos_pago}, {telefono_empresa}, {email_empresa}.
"""

import re
from typing import Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calculos import clp
from app.database import get_db
from app.models.cobranza import Cobranza
from app.models.empresa import Empresa
from app.planes import requiere_funcion
from app.security import usuario_autorizado

router = APIRouter(
    tags=["Mensajes"],
    dependencies=[Depends(usuario_autorizado), Depends(requiere_funcion("mensaje_pago"))],
)

PLANTILLA_DEFECTO = (
    "Estimado(a) {deudor}:\n\n"
    "Le escribimos de {empresa} por la deuda N° {numero} con {cliente}, "
    "cuyo saldo a la fecha es de {saldo}.\n\n"
    "Puede pagar por transferencia a:\n{datos_pago}\n\n"
    "Una vez realizado el pago, envíenos el comprobante por este medio para "
    "registrarlo y dar por cerrada su cobranza.\n\n"
    "Atentamente,\n{empresa}"
)

MARCADORES = ("deudor", "nombre", "saldo", "numero", "id_externo", "cliente", "empresa",
              "datos_pago", "telefono_empresa", "email_empresa")


class MensajePago(BaseModel):
    texto: str
    asunto: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    whatsapp_url: Optional[str] = None
    mailto_url: Optional[str] = None
    falta_datos_pago: bool = False


def telefono_whatsapp(numero: str) -> Optional[str]:
    """'+56 9 1234 5678' / '912345678' / '12345678' → '56912345678'."""
    digitos = re.sub(r"\D", "", numero or "")
    if digitos.startswith("56") and len(digitos) == 11:
        return digitos
    if len(digitos) == 9 and digitos.startswith("9"):
        return "56" + digitos
    if len(digitos) == 8:
        return "569" + digitos
    return digitos if len(digitos) >= 10 else None


def rellenar(plantilla: str, valores: dict) -> str:
    """Reemplaza {marcador} conocidos; deja intacto cualquier otro texto entre llaves."""
    return re.sub(r"\{(\w+)\}", lambda m: str(valores.get(m.group(1), m.group(0))), plantilla)


@router.get("/api/cobranzas/{cobranza_id}/mensaje-pago", response_model=MensajePago)
def mensaje_pago(cobranza_id: UUID, request: Request, db: Session = Depends(get_db)):
    cob = db.get(Cobranza, cobranza_id)
    if cob is None:
        raise HTTPException(status_code=404, detail="Cobranza no encontrada")
    emp = db.query(Empresa).first()
    org = request.state.organizacion
    empresa = (emp.nombre_fantasia or emp.razon_social) if emp else org.nombre
    cliente = cob.cliente
    datos_pago = ((cliente.instrucciones_pago if cliente else None)
                  or (emp.instrucciones_pago if emp else None) or "").strip()
    deudor = cob.deudor

    valores = {
        "deudor": deudor.nombre if deudor else "",
        "nombre": (deudor.nombre.split()[0].capitalize() if deudor and deudor.nombre else ""),
        "saldo": clp(cob.monto_actual),
        "numero": cob.numero,
        "id_externo": cob.id_externo or "",
        "cliente": (cliente.nombre_fantasia or cliente.razon_social) if cliente else "",
        "empresa": empresa,
        "datos_pago": datos_pago or "[faltan los datos de transferencia: cárgalos en Mi empresa]",
        "telefono_empresa": (emp.telefonos if emp else "") or "",
        "email_empresa": (emp.emails if emp else "") or "",
    }
    plantilla = (org.configuracion or {}).get("plantilla_mensaje_pago") or PLANTILLA_DEFECTO
    texto = rellenar(plantilla, valores)
    asunto = f"Cobranza N° {cob.numero} - {valores['cliente']}".strip(" -")

    telefono = email = None
    if deudor:
        activos = [c for c in deudor.contactos if c.activo]
        for tipo in ("whatsapp", "celular", "telefono"):
            telefono = telefono or next((c.valor for c in activos if c.tipo == tipo), None)
        email = next((c.valor for c in activos if c.tipo == "email"), None)

    numero_wa = telefono_whatsapp(telefono) if telefono else None
    return MensajePago(
        texto=texto,
        asunto=asunto,
        telefono=telefono,
        email=email,
        whatsapp_url=(f"https://wa.me/{numero_wa}?text={quote(texto)}" if numero_wa
                      else f"https://wa.me/?text={quote(texto)}"),
        mailto_url=(f"mailto:{quote(email or '')}?subject={quote(asunto)}&body={quote(texto)}"),
        falta_datos_pago=not datos_pago,
    )
