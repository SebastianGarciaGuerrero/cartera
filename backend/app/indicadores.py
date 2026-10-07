"""
UF del día (y de cualquier fecha) con caché en la base.

La primera vez que alguien pide la UF de una fecha se consulta afuera
(mindicador.cl y, si falla, boostr.cl: ambas coinciden con el SII) y se
guarda en `indicadores`; las siguientes veces sale de la base, para todas
las organizaciones.
"""

import json
import logging
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from app.models.agenda import Indicador
from app.tenancy import sesion_sistema

log = logging.getLogger("cartera.indicadores")
ZONA_CHILE = ZoneInfo("America/Santiago")


def hoy_chile() -> date:
    return datetime.now(ZONA_CHILE).date()


def _pedir_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cartera/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 (URL fija)
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # red caída, timeout, JSON inválido
        log.warning("No se pudo consultar %s: %s", url, e)
        return None


def _desde_mindicador(fecha: date) -> Optional[Decimal]:
    datos = _pedir_json(f"https://mindicador.cl/api/uf/{fecha.strftime('%d-%m-%Y')}")
    serie = (datos or {}).get("serie") or []
    if serie and serie[0].get("valor"):
        return Decimal(str(serie[0]["valor"]))
    return None


def _desde_boostr(fecha: date) -> Optional[Decimal]:
    if fecha != hoy_chile():
        return None  # esta fuente solo entrega el valor del día
    datos = _pedir_json("https://api.boostr.cl/economy/indicators.json")
    uf = ((datos or {}).get("data") or {}).get("uf") or {}
    return Decimal(str(uf["value"])) if uf.get("value") else None


FUENTES = [("mindicador.cl", _desde_mindicador), ("boostr.cl", _desde_boostr)]


def obtener_uf(fecha: Optional[date] = None) -> Optional[Indicador]:
    """UF de la fecha (por defecto hoy en Chile). None si no hay forma de saberla."""
    fecha = fecha or hoy_chile()
    with sesion_sistema() as db:
        guardado = db.get(Indicador, ("uf", fecha))
        if guardado is not None:
            db.expunge(guardado)
            return guardado
        for nombre, fuente in FUENTES:
            valor = fuente(fecha)
            if valor and valor > 0:
                indicador = Indicador(codigo="uf", fecha=fecha, valor=valor, fuente=nombre)
                db.merge(indicador)
                db.commit()
                return indicador
    return None
