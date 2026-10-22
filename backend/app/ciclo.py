"""
Ciclo de vida de una cobranza: en qué etapa está y por dónde pasó.

    INGRESO → EXTRAJUDICIAL → PARA DEMANDA → JUDICIAL → TÉRMINO
                                             demanda
                                             notificación
                                             embargo
                                             excepciones y sentencia
                                             remate y pago

- `cobranzas.etapa` guarda la etapa abierta (ingreso / extrajudicial /
  para_demanda / judicial). La primera gestión pasa una cobranza de ingreso
  a extrajudicial (trigger); a judicial se llega al presentar la demanda
  (app/judicial.py). De judicial no se vuelve: lo impide la base.
- Dentro de judicial, el paso lo da la causa (`causas.etapa_procesal`, que
  sigue al último trámite registrado).
- El término sale del estado de la cobranza (pagada / archivada / castigo)
  con su `motivo_cierre`.

Cada cambio de etapa queda en `cambios_etapa` (lo escribe el trigger con el
usuario y el motivo que se le pasan por set_config).
"""

from datetime import date
from typing import List, Optional
from uuid import UUID


from sqlalchemy import text
from sqlalchemy.orm import Session

from app.indicadores import hoy_chile
from app.models.cobranza import Cobranza
from app.operaciones import sumar_meses

ETAPAS = ("ingreso", "extrajudicial", "para_demanda", "judicial")
ESTADOS_TERMINALES = ("pagada", "archivada", "castigo")

# Pasos de la barra, en orden. "grupo" agrupa los pasos judiciales.
PASOS = [
    ("ingreso", "Ingreso", None),
    ("extrajudicial", "Extrajudicial", None),
    ("para_demanda", "Para demanda", None),
    ("demanda", "Demanda", "judicial"),
    ("notificacion", "Notificación", "judicial"),
    ("embargo", "Embargo", "judicial"),
    ("defensa", "Excepciones y sentencia", "judicial"),
    ("remate", "Remate y pago", "judicial"),
    ("termino", "Término", None),
]
_ORDEN = {clave: i for i, (clave, _n, _g) in enumerate(PASOS)}

# Por qué terminó una cobranza (cobranzas.motivo_cierre).
MOTIVOS_CIERRE = {
    "pagada": "Pagada",
    "avenimiento_cumplido": "Avenimiento cumplido",
    "inubicable": "Deudor inubicable",
    "sin_bienes": "Sin bienes embargables",
    "liquidacion": "Deudor en liquidación (quiebra)",
    "fallecido": "Deudor fallecido",
    "antieconomico": "Antieconómico seguir",
    "prescrita": "Acción prescrita",
    "abandono": "Abandono del procedimiento",
    "desistida": "Desistimiento",
    "devuelta_cliente": "Devuelta al cliente",
    "suspendida_cliente": "Suspendida por el cliente",
    "otro": "Otro motivo",
}

# Prescripción de la acción ejecutiva por tipo de documento, en meses desde
# el vencimiento (cheque: desde el protesto). Referencial: el abogado debe
# confirmarlo en cada caso. Se usa solo para AVISAR antes de demandar.
MESES_PRESCRIPCION = {
    "cheque": 12,
    "pagare": 12,
    "letra": 12,
    "factura": 12,
}
MESES_PRESCRIPCION_OTROS = 36  # acción ejecutiva general (art. 2515 Código Civil)
DIAS_AVISO_PRESCRIPCION = 90


class ErrorEtapa(ValueError):
    """Cambio de etapa que no corresponde (se responde 400)."""


def prescripcion(tipo_documento: Optional[str], vencimiento: Optional[date]) -> Optional[date]:
    if vencimiento is None:
        return None
    return sumar_meses(vencimiento, MESES_PRESCRIPCION.get(tipo_documento or "", MESES_PRESCRIPCION_OTROS))


def fecha_prescripcion(cobranza: Cobranza) -> Optional[date]:
    return prescripcion(cobranza.tipo_documento, cobranza.fecha_vencimiento_documento)


def fijar_contexto(db: Session, usuario_id: Optional[UUID], motivo: Optional[str]) -> None:
    """Quién y por qué, para el historial que escribe el trigger."""
    db.execute(
        text("SELECT set_config('app.usuario_id', :u, true), set_config('app.motivo_etapa', :m, true)"),
        {"u": str(usuario_id) if usuario_id else "", "m": (motivo or "")[:300]},
    )


def cambiar_etapa(db: Session, cobranza: Cobranza, nueva: str,
                  usuario_id: Optional[UUID], motivo: Optional[str] = None) -> None:
    """
    Mueve la cobranza de etapa (dentro de la transacción en curso, sin commit).
    A judicial solo se entra presentando una demanda (crear_causa).
    """
    if nueva not in ETAPAS:
        raise ErrorEtapa(f"Etapa desconocida: {nueva}")
    if cobranza.etapa == nueva:
        return
    if cobranza.etapa == "judicial":
        raise ErrorEtapa("La cobranza ya está en judicial: hay una demanda de por medio y no puede volver atrás.")
    if cobranza.estado in ESTADOS_TERMINALES:
        raise ErrorEtapa("La cobranza está cerrada; reábrala antes de cambiar su etapa.")
    fijar_contexto(db, usuario_id, motivo)
    cobranza.etapa = nueva
    db.flush()
    fijar_contexto(db, usuario_id, "")


def _paso_actual(cobranza: Cobranza, etapa_procesal: Optional[str]) -> str:
    if cobranza.estado in ESTADOS_TERMINALES:
        return "termino"
    if cobranza.etapa == "judicial":
        return etapa_procesal or "demanda"
    return cobranza.etapa


def estado_ciclo(db: Session, cobranza: Cobranza) -> dict:
    """Todo lo que necesita la barra del ciclo de vida de una cobranza."""
    causas = db.execute(text("""
        SELECT ca.id, ca.rol, ca.procedimiento, ca.etapa_procesal, ca.estado, ca.resultado,
               ca.fecha_ingreso, ca.fecha_termino, t.nombre AS tribunal
        FROM causa_cobranzas cc
        JOIN causas ca ON ca.id = cc.causa_id
        LEFT JOIN tribunales t ON t.id = ca.tribunal_id
        WHERE cc.cobranza_id = :c
        ORDER BY (ca.estado = 'vigente') DESC, ca.fecha_ingreso DESC
    """), {"c": cobranza.id}).mappings().all()
    principal = causas[0] if causas else None
    etapa_procesal = principal["etapa_procesal"] if principal else None
    actual = _paso_actual(cobranza, etapa_procesal)

    # Hasta dónde llegó antes de terminar (para marcar lo que se saltó).
    alcanzado = etapa_procesal if cobranza.etapa == "judicial" else cobranza.etapa
    if cobranza.etapa == "judicial" and not alcanzado:
        alcanzado = "demanda"
    pasos = []
    for clave, nombre, grupo in PASOS:
        if actual == "termino":
            if clave == "termino":
                estado = "actual"
            elif _ORDEN[clave] <= _ORDEN[alcanzado]:
                estado = "hecho"
            else:
                estado = "omitido"
        elif clave == actual:
            estado = "actual"
        elif _ORDEN[clave] < _ORDEN[actual]:
            estado = "hecho"
        else:
            estado = "pendiente"
        pasos.append({"clave": clave, "nombre": nombre, "grupo": grupo, "estado": estado})

    historial = db.execute(text("""
        SELECT ce.etapa_anterior, ce.etapa_nueva, ce.motivo, ce.created_at, u.nombre AS usuario
        FROM cambios_etapa ce
        LEFT JOIN usuarios u ON u.id = ce.usuario_id
        WHERE ce.cobranza_id = :c
        ORDER BY ce.created_at
    """), {"c": cobranza.id}).mappings().all()

    hoy = hoy_chile()
    prescribe = fecha_prescripcion(cobranza) if cobranza.etapa != "judicial" else None
    return {
        "cobranza_id": cobranza.id,
        "etapa": cobranza.etapa,
        "etapa_desde": cobranza.etapa_desde,
        "dias_en_etapa": (hoy - cobranza.etapa_desde).days if cobranza.etapa_desde else None,
        "paso_actual": actual,
        "pasos": pasos,
        "estado": cobranza.estado,
        "motivo_cierre": cobranza.motivo_cierre,
        "motivo_cierre_nombre": MOTIVOS_CIERRE.get(cobranza.motivo_cierre or ""),
        "fecha_cierre": cobranza.fecha_cierre,
        "fecha_prescripcion": prescribe,
        "prescripcion_proxima": bool(
            prescribe and cobranza.estado not in ESTADOS_TERMINALES
            and (prescribe - hoy).days <= DIAS_AVISO_PRESCRIPCION
        ),
        "causas": [dict(c) for c in causas],
        "historial": [dict(h) for h in historial],
    }


def cobranzas_para_demanda(db: Session, organizacion_id: UUID, hoy: date, *,
                           preparacion: bool, limite: int = 500) -> List[dict]:
    """
    preparacion=True: las que el equipo ya pasó a 'para demanda'.
    preparacion=False: las que según la regla de su cliente ya deberían
    prepararse: activas (sin acuerdo vigente), en ingreso o extrajudicial y
    con más días desde el ingreso que los de clientes.dias_para_demanda.
    """
    if preparacion:
        filtro = "c.etapa = 'para_demanda' AND c.estado IN ('activa', 'acuerdo_pago')"
        orden = "c.etapa_desde"
    else:
        filtro = """c.estado = 'activa' AND c.etapa IN ('ingreso', 'extrajudicial')
          AND cl.dias_para_demanda IS NOT NULL
          AND c.fecha_ingreso + cl.dias_para_demanda <= :hoy"""
        orden = "c.fecha_ingreso"
    filas = db.execute(text(f"""
        SELECT c.id, c.numero, c.monto_actual, c.fecha_ingreso, c.etapa, c.etapa_desde,
               c.tipo_documento, c.fecha_vencimiento_documento,
               d.nombre AS deudor, d.rut AS deudor_rut,
               COALESCE(cl.nombre_fantasia, cl.razon_social) AS cliente,
               cl.dias_para_demanda,
               (:hoy - c.fecha_ingreso) AS dias_en_cartera,
               (SELECT max(g.fecha_gestion)::date FROM gestiones g
                WHERE g.organizacion_id = c.organizacion_id AND g.cobranza_id = c.id) AS ultima_gestion
        FROM cobranzas c
        JOIN clientes cl ON cl.id = c.cliente_id
        JOIN deudores d ON d.id = c.deudor_id
        WHERE c.organizacion_id = :org AND {filtro}
        ORDER BY {orden}
        LIMIT :lim
    """), {"org": organizacion_id, "hoy": hoy, "lim": limite}).mappings().all()
    return [{**f, "fecha_prescripcion": prescripcion(f["tipo_documento"], f["fecha_vencimiento_documento"])}
            for f in filas]
