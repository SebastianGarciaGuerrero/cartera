"""
Simulador de cartera: llena una organización de prueba con N años de
cobranza extrajudicial y judicial, para medir la velocidad del sistema con
volúmenes reales.

Las proporciones salen de lo medido en el sistema anterior de un estudio
(22 años de datos), por año y a escala 1:
  - ~950 cobranzas nuevas, cada deudor con ~1,35 cobranzas;
  - ~12 gestiones extrajudiciales por cobranza (mediana 10, p90 30);
  - ~50 % llega a demanda; ~15 trámites por causa, la mayoría
    observaciones; ~2,5 gastos por causa;
  - ~25 % de las cobranzas recibe pagos (acuerdos en cuotas y abonos).

Todos los nombres, RUT, montos y textos son ficticios. Inserta directo en
la base (como dueño de las tablas, sin pasar por la API) para que 5 años
se generen en segundos; respeta las mismas reglas que la app (FK
compuestas, catálogos, triggers de número correlativo).

Uso (desde backend, con el venv y DATABASE_URL de la base de PRUEBA):
  python -m app.cli simular --anios 5 [--escala 1] [--semilla 7]
  python -m app.cli medir-rendimiento --email admin@simulacion.cl --password ...

Nunca correrlo contra la base de producción de un estudio: crea una
organización aparte ("simulacion"), pero igual ocupa espacio y CPU.
"""

from __future__ import annotations

import math
import random
import secrets
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from psycopg2.extras import execute_values

from app.indicadores import hoy_chile
from app.rut import calcular_dv

SLUG = "simulacion"
EMAIL_ADMIN = "admin@simulacion.cl"

NOMBRES = ["María", "José", "Juan", "Ana", "Luis", "Carmen", "Pedro", "Francisca", "Diego", "Camila",
           "Jorge", "Valentina", "Carlos", "Javiera", "Felipe", "Constanza", "Cristián", "Daniela",
           "Rodrigo", "Catalina", "Patricio", "Fernanda", "Sebastián", "Paula", "Matías", "Isidora",
           "Nicolás", "Antonia", "Ricardo", "Gabriela", "Héctor", "Rosa", "Manuel", "Teresa"]
APELLIDOS = ["González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva", "Martínez",
             "Sepúlveda", "Morales", "Rodríguez", "López", "Fuentes", "Hernández", "Torres", "Araya",
             "Flores", "Espinoza", "Valenzuela", "Castillo", "Tapia", "Reyes", "Gutiérrez", "Castro",
             "Pizarro", "Álvarez", "Vásquez", "Sánchez", "Fernández", "Ramírez", "Carrasco", "Gómez",
             "Cortés", "Herrera", "Núñez", "Jara", "Vergara", "Rivera", "Figueroa"]
COMUNAS = ["Valparaíso", "Viña del Mar", "Quilpué", "Villa Alemana", "Concón", "Limache", "Quillota",
           "La Calera", "San Antonio", "Los Andes", "San Felipe", "Casablanca", "Santiago"]
CALLES = ["Av. Argentina", "Pedro Montt", "Av. España", "Errázuriz", "Blanco", "Condell", "Av. Libertad",
          "Los Carrera", "Freire", "Av. Valparaíso", "Baquedano", "O'Higgins"]
RUBROS_CLIENTE = ["Clínica", "Centro Médico", "Universidad", "Instituto", "Distribuidora", "Comercial",
                  "Inmobiliaria", "Automotriz", "Ferretería", "Constructora"]

# Documento que respalda la deuda (proporciones del sistema anterior).
DOCUMENTOS = [("factura", 47), ("cheque", 25), ("pagare", 13), ("otro", 7), ("letra", 7), ("contrato", 1)]
# Procedimiento según el documento.
PROCEDIMIENTO_DOC = {
    "cheque": [("notificacion_cheque", 80), ("querella", 8), ("ejecutivo", 12)],
    "factura": [("notificacion_factura", 55), ("confesion_deuda", 35), ("ordinario", 10)],
    "pagare": [("ejecutivo", 85), ("notificacion_letra", 15)],
    "letra": [("notificacion_letra", 70), ("ejecutivo", 30)],
    "otro": [("confesion_deuda", 60), ("ordinario", 30), ("exhorto", 10)],
    "contrato": [("ordinario", 70), ("sumario", 30)],
}
GESTIONES = [
    ("llamada", 30, ["Se llama al deudor, no contesta.", "Contesta, indica que pagará a fin de mes.",
                     "Habla con familiar, deja recado.", "Deudor pide plazo hasta su próximo sueldo.",
                     "Se explica el estado de la deuda y las opciones de pago."]),
    ("no_contesta", 22, ["Fono no contesta.", "Buzón de voz.", "Celular apagado.", "Fono fuera de servicio."]),
    ("whatsapp", 14, ["Se envía estado de deuda por WhatsApp.", "Deudor responde por WhatsApp, pide datos de transferencia.",
                      "Mensaje leído sin respuesta."]),
    ("email", 8, ["Se envía estado de cuenta por correo.", "Se envía recordatorio de pago."]),
    ("carta", 8, ["Se envía carta de cobranza.", "Se envía carta de ultimátum.", "Carta devuelta por domicilio desconocido."]),
    ("visita", 4, ["Se visita en terreno, deudor vive allí.", "Visita en terreno: desconocido en el domicilio."]),
    ("promesa_pago", 7, ["Se compromete a pagar el próximo viernes.", "Promete abonar la mitad este mes."]),
    ("negativa_pago", 4, ["Se niega a pagar, indica que no reconoce la deuda.", "Se niega a pagar extrajudicialmente."]),
    ("nota", 3, ["Se solicitan antecedentes al cliente.", "Cliente confirma que la deuda sigue vigente."]),
]
OBSERVACIONES_JUD = ["Se revisa el expediente.", "Cumple lo ordenado.", "Se consulta estado de la diligencia al receptor.",
                     "Se acompaña copia de la cédula.", "Se solicita certificación.", "Pendiente resolución del tribunal.",
                     "Se reitera solicitud.", "Se revisa estado diario.", "Se envía copia al cliente."]
RESULTADO_CAUSA = [("castigo", 45), ("pagada", 25), ("archivada", 15), ("avenimiento_cumplido", 10), ("desistida", 5)]
MOTIVO_CASTIGO = [("inubicable", 40), ("sin_bienes", 40), ("antieconomico", 10), ("fallecido", 5), ("liquidacion", 5)]
FORMAS = [("transferencia", 55), ("efectivo", 15), ("deposito", 12), ("cheque", 10), ("flow", 8)]
TIPOS_BIEN = [("muebles", 45), ("vehiculo", 30), ("inmueble", 10), ("cuenta_bancaria", 10), ("remuneraciones", 5)]


def _elegir(r: random.Random, opciones):
    return r.choices([o[0] for o in opciones], weights=[o[1] for o in opciones])[0]


def _rut(n: int) -> str:
    return f"{n}-{calcular_dv(n)}"


def _entre(r: random.Random, a: date, b: date) -> date:
    if b <= a:
        return a
    return a + timedelta(days=r.randint(0, (b - a).days))


def _clp(r: random.Random, mediana: float, sigma: float = 0.9, minimo: int = 5000) -> Decimal:
    return Decimal(max(minimo, int(round(math.exp(math.log(mediana) + r.gauss(0, sigma)), -2))))


def _ts(d: date, r: random.Random) -> datetime:
    return datetime(d.year, d.month, d.day, r.randint(12, 23), r.randint(0, 59), tzinfo=timezone.utc)


@dataclass
class Lotes:
    """Filas a insertar, por tabla, en orden de dependencias."""
    filas: dict = field(default_factory=lambda: {t: [] for t in (
        "clientes", "deudores", "contactos_deudor", "cobranzas", "causas", "causa_cobranzas",
        "gestiones", "cambios_etapa", "acuerdos_pago", "cuotas", "pagos", "tramites", "embargos",
        "rendiciones_gastos", "gastos")})

    def agregar(self, tabla: str, fila: dict) -> None:
        self.filas[tabla].append(fila)


def _preparar_organizacion(cur, password: str) -> dict:
    """Crea (o reutiliza) la organización de simulación con su equipo."""
    from app.security import hashear_password

    cur.execute("SELECT id FROM organizaciones WHERE slug = %s", (SLUG,))
    fila = cur.fetchone()
    if fila:
        org = fila[0]
        cur.execute("SELECT count(*) FROM cobranzas WHERE organizacion_id = %s", (org,))
        if cur.fetchone()[0]:
            raise SystemExit("La organización 'simulacion' ya tiene datos. Use una base nueva para simular de nuevo.")
    else:
        org = str(uuid.uuid4())
        cur.execute("""INSERT INTO organizaciones (id, nombre, slug, plan, estado, numero_cobranza_siguiente)
                       VALUES (%s, 'Estudio Simulación', %s, 'premium', 'activa', 10001)""", (org, SLUG))
        cur.execute("""INSERT INTO empresa (organizacion_id, razon_social, nombre_fantasia, wordmark, firma_documentos,
                                            instrucciones_pago)
                       VALUES (%s, 'Estudio Simulación SpA', 'Estudio Simulación', 'ESTUDIO SIMULACIÓN',
                               'Estudio Simulación', 'Transferencia a la cuenta del estudio')""", (org,))
    cur.execute("SELECT id, nombre FROM roles")
    roles = {n: i for i, n in cur.fetchall()}
    equipo = [("Administración Simulación", EMAIL_ADMIN, "admin")]
    equipo += [(f"Ejecutivo {i}", f"ejecutivo{i}@simulacion.cl", "operador") for i in range(1, 7)]
    equipo += [(f"Abogado {i}", f"abogado{i}@simulacion.cl", "abogado") for i in range(1, 3)]
    equipo += [(f"Procurador {i}", f"procurador{i}@simulacion.cl", "procurador") for i in range(1, 3)]
    clave = hashear_password(password)
    usuarios: dict[str, list] = {"admin": [], "operador": [], "abogado": [], "procurador": []}
    for nombre, email, rol in equipo:
        cur.execute("SELECT id FROM usuarios WHERE lower(email) = %s", (email,))
        existe = cur.fetchone()
        if existe:
            cur.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s", (clave, existe[0]))
            uid = existe[0]
        else:
            uid = str(uuid.uuid4())
            cur.execute("""INSERT INTO usuarios (id, organizacion_id, nombre, email, password_hash, rol_id)
                           VALUES (%s, %s, %s, %s, %s, %s)""", (uid, org, nombre, email, clave, roles[rol]))
        usuarios[rol].append(str(uid))
    return {"org": str(org), "usuarios": usuarios}


def simular(conexion, anios: int = 5, escala: float = 1.0, semilla: int = 7,
            password: Optional[str] = None, informar=print) -> dict:
    """
    Genera la cartera simulada. `conexion` es una conexión psycopg2 con
    permisos de dueño de las tablas. Devuelve un resumen con los conteos.
    """
    r = random.Random(semilla)
    _ROLES.clear()
    hoy = hoy_chile()
    inicio = hoy - timedelta(days=round(365.25 * anios))
    password = password or secrets.token_urlsafe(12)
    cur = conexion.cursor()
    base = _preparar_organizacion(cur, password)
    org, usuarios = base["org"], base["usuarios"]
    ejecutivos, abogados, procuradores = usuarios["operador"], usuarios["abogado"], usuarios["procurador"]
    admin = usuarios["admin"][0]

    cur.execute("SELECT codigo, id FROM tipos_gestion WHERE organizacion_id IS NULL AND codigo IS NOT NULL")
    tipos_gestion = dict(cur.fetchall())
    cur.execute("""SELECT id, codigo, etapa, plazo_dias, siguiente_id, genera_gasto, resultado
                   FROM tipos_tramite WHERE organizacion_id IS NULL""")
    tramites_cat = {f[0]: f for f in cur.fetchall()}
    por_codigo = {f[1]: f for f in tramites_cat.values()}
    cur.execute("SELECT id FROM tribunales WHERE organizacion_id IS NULL AND competencia = 'civil'")
    tribunales = [f[0] for f in cur.fetchall()]
    tribunales_principales = tribunales[:13]  # Valparaíso, Viña y alrededores: la mayoría de las causas

    lotes = Lotes()
    # ---------------------------------------------------------------- clientes
    clientes = []
    for i in range(max(3, round(25 * min(escala, 4)))):
        cid = str(uuid.uuid4())
        rubro = RUBROS_CLIENTE[i % len(RUBROS_CLIENTE)]
        nombre = f"{rubro} {r.choice(APELLIDOS)} {r.choice(['SpA', 'Ltda.', 'S.A.'])}"
        dias = r.choice([None, 0, 90, 120, 120, 150, 180])
        lotes.agregar("clientes", {"id": cid, "organizacion_id": org, "rut": _rut(76_000_000 + i * 7919),
                                   "razon_social": nombre, "nombre_fantasia": f"{rubro} {i + 1}",
                                   "comuna": r.choice(COMUNAS), "dias_para_demanda": dias})
        clientes.append((cid, r.paretovariate(1.2)))  # pocos clientes con mucha cartera
    pesos_clientes = [p for _, p in clientes]

    # ---------------------------------------------------------------- cobranzas
    n_cobranzas = max(5, round(950 * escala * anios))
    deudores: list[dict] = []
    contador_rut = 9_000_000
    contador_externo = 100_000
    gastos_por_cliente: dict[str, list] = {}

    for i in range(n_cobranzas):
        # Un deudor nuevo o, a veces, uno que ya debía (reincidente).
        if deudores and r.random() < 0.26:
            deudor = r.choice(deudores[-400:])
        else:
            contador_rut += r.randint(1, 4000)
            nombre = f"{r.choice(NOMBRES)} {r.choice(NOMBRES) if r.random() < 0.5 else ''} {r.choice(APELLIDOS)} {r.choice(APELLIDOS)}"
            deudor = {"id": str(uuid.uuid4()), "organizacion_id": org, "rut": _rut(contador_rut),
                      "nombre": " ".join(nombre.split()), "comuna": r.choice(COMUNAS),
                      "direccion": f"{r.choice(CALLES)} {r.randint(10, 3999)}", "ciudad": "Valparaíso",
                      "en_boletin_comercial": r.random() < 0.15}
            deudores.append(deudor)
            lotes.agregar("deudores", deudor)
            lotes.agregar("contactos_deudor", {"id": str(uuid.uuid4()), "organizacion_id": org,
                                               "deudor_id": deudor["id"], "tipo": "celular",
                                               "valor": f"+569{r.randint(10_000_000, 99_999_999)}"})
            if r.random() < 0.35:
                lotes.agregar("contactos_deudor", {"id": str(uuid.uuid4()), "organizacion_id": org,
                                                   "deudor_id": deudor["id"], "tipo": "email",
                                                   "valor": f"deudor{contador_rut}@correo-ficticio.cl"})

        cliente_id = r.choices(clientes, weights=pesos_clientes)[0][0]
        # Algo más de cartera en los años recientes.
        fecha_ingreso = inicio + timedelta(days=int((hoy - inicio).days * (r.random() ** 0.9)))
        documento = _elegir(r, DOCUMENTOS)
        capital = _clp(r, 345_000)
        vencimiento = fecha_ingreso - timedelta(days=r.randint(30, 300))
        ejecutivo = r.choice(ejecutivos)
        contador_externo += r.randint(1, 30)
        cob = {"id": str(uuid.uuid4()), "organizacion_id": org, "cliente_id": cliente_id,
               "deudor_id": deudor["id"], "id_externo": str(contador_externo),
               "monto_original": capital, "monto_actual": capital, "capital": capital,
               "fecha_ingreso": fecha_ingreso, "tipo_documento": documento,
               "numero_documento": str(r.randint(1000, 999999)), "fecha_vencimiento_documento": vencimiento,
               "estado": "activa", "tipo": "extrajudicial", "etapa": "ingreso", "etapa_desde": fecha_ingreso,
               "motivo_cierre": None, "fecha_cierre": None, "ejecutivo_id": ejecutivo,
               "created_at": _ts(fecha_ingreso, r)}

        # ---------------------------------------------- gestiones extrajudiciales
        n_gest = min(60, max(0, int(r.lognormvariate(math.log(10), 0.8))))
        fecha = fecha_ingreso
        ultima = None
        limite_extra = min(hoy, fecha_ingreso + timedelta(days=r.randint(60, 420)))
        for g in range(n_gest):
            fecha = fecha + timedelta(days=r.randint(0, max(1, (limite_extra - fecha_ingreso).days // max(1, n_gest)) * 2))
            if fecha > limite_extra:
                break
            codigo = _elegir(r, [(c, p) for c, p, _ in GESTIONES])
            texto = r.choice(next(t for c, _, t in GESTIONES if c == codigo))
            proximo = None
            if codigo == "promesa_pago" or r.random() < 0.25:
                proximo = fecha + timedelta(days=r.randint(1, 15))
            ultima = {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                      "usuario_id": ejecutivo, "fecha_gestion": _ts(fecha, r), "tipo_id": tipos_gestion.get(codigo),
                      "descripcion": texto, "fecha_proximo_contacto": proximo, "created_at": _ts(fecha, r)}
            lotes.agregar("gestiones", ultima)
        if ultima is not None:
            cob["etapa"] = "extrajudicial"
            lotes.agregar("cambios_etapa", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                            "etapa_anterior": "ingreso", "etapa_nueva": "extrajudicial",
                                            "usuario_id": ejecutivo, "motivo": "Primera gestión registrada",
                                            "created_at": _ts(fecha_ingreso, r)})

        dias_en_cartera = (hoy - fecha_ingreso).days
        destino = r.random()
        # ------------------------------------------------ acuerdo en cuotas
        if destino < 0.16 and ultima is not None and dias_en_cartera > 20:
            _simular_acuerdo(r, lotes, org, cob, ejecutivo, tipos_gestion, hoy)
        elif destino < 0.24 and ultima is not None:
            _simular_abonos(r, lotes, org, cob, ejecutivo, tipos_gestion, hoy)
        # ------------------------------------------------ demanda
        elif destino < 0.74 and dias_en_cartera > 100 and cob["estado"] == "activa":
            _simular_causa(r, lotes, org, cob, deudor, tramites_cat, por_codigo,
                           tribunales_principales if r.random() < 0.85 else tribunales,
                           abogados, procuradores, admin, tipos_gestion, hoy, gastos_por_cliente)
        elif cob["etapa"] == "extrajudicial" and dias_en_cartera > 90 and r.random() < 0.08:
            cob["etapa"], cob["etapa_desde"] = "para_demanda", hoy - timedelta(days=r.randint(1, 40))
        elif dias_en_cartera > 500 and r.random() < 0.35:
            cob["estado"], cob["motivo_cierre"] = "castigo", _elegir(r, MOTIVO_CASTIGO)
            cob["fecha_cierre"] = fecha_ingreso + timedelta(days=r.randint(200, 480))

        # Agenda viva: parte de la cartera abierta tiene compromisos cerca de hoy.
        if cob["estado"] in ("activa", "acuerdo_pago") and ultima is not None and r.random() < 0.3:
            ultima["fecha_proximo_contacto"] = hoy + timedelta(days=r.randint(-10, 14))
        lotes.agregar("cobranzas", cob)

    _rendir_gastos(r, lotes, org, gastos_por_cliente, admin, hoy)

    # ---------------------------------------------------------------- insertar
    t0 = time.perf_counter()
    conteos = {}
    for tabla, filas in lotes.filas.items():
        if not filas:
            conteos[tabla] = 0
            continue
        columnas = list(filas[0].keys())
        for f in filas[1:]:
            for c in f:
                if c not in columnas:
                    columnas.append(c)
        valores = [tuple(f.get(c) for c in columnas) for f in filas]
        execute_values(cur, f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES %s", valores, page_size=2000)
        conteos[tabla] = len(filas)
        informar(f"  {tabla:<20} {len(filas):>9,}".replace(",", "."))
    cur.execute("ANALYZE")
    conexion.commit()
    conteos["segundos_insercion"] = round(time.perf_counter() - t0, 1)
    conteos["password"] = password
    return conteos


def _simular_acuerdo(r, lotes, org, cob, usuario, tipos_gestion, hoy) -> None:
    n = r.choice([3, 4, 6, 6, 8, 10, 12])
    capital = Decimal(cob["monto_actual"])
    total = (capital * Decimal("1.12")).quantize(Decimal(1))
    fecha_acuerdo = cob["fecha_ingreso"] + timedelta(days=r.randint(10, 120))
    if fecha_acuerdo >= hoy:
        fecha_acuerdo = hoy - timedelta(days=1)
    primera = fecha_acuerdo + timedelta(days=30)
    acuerdo_id = str(uuid.uuid4())
    valor = (total / n).quantize(Decimal(1))
    cap_cuota = (capital / n).quantize(Decimal(1))
    pagado_capital = Decimal(0)
    estado_acuerdo = "vigente"
    sigue_pagando = True
    for k in range(n):
        vence = primera + timedelta(days=30 * k)
        monto = valor if k < n - 1 else total - valor * (n - 1)
        capital_k = cap_cuota if k < n - 1 else capital - cap_cuota * (n - 1)
        cuota = {"id": str(uuid.uuid4()), "organizacion_id": org, "acuerdo_id": acuerdo_id, "numero_cuota": k + 1,
                 "monto": monto, "fecha_vencimiento": vence, "monto_pagado": Decimal(0), "estado": "pendiente",
                 "capital": capital_k, "honorarios": monto - capital_k, "intereses": Decimal(0),
                 "gastos_judiciales": Decimal(0), "comision": Decimal(0)}
        if sigue_pagando and r.random() < 0.06 + 0.02 * k:
            sigue_pagando = False
        fecha_pago = vence + timedelta(days=r.randint(-5, 10))
        if sigue_pagando and fecha_pago <= hoy:
            cuota["monto_pagado"], cuota["estado"] = monto, "pagada"
            pagado_capital += capital_k
            lotes.agregar("pagos", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                    "cuota_id": cuota["id"], "fecha_pago": fecha_pago, "monto": monto,
                                    "capital": capital_k, "honorarios": monto - capital_k, "intereses": Decimal(0),
                                    "gastos_judiciales": Decimal(0), "forma_pago": _elegir(r, FORMAS),
                                    "estado_pago": "cuota", "usuario_id": usuario, "created_at": _ts(fecha_pago, r)})
        elif vence < hoy:
            cuota["estado"] = "vencida"
            if (hoy - vence).days > 60:
                estado_acuerdo = "incumplido"
        lotes.agregar("cuotas", cuota)
    if all(c["estado"] == "pagada" for c in lotes.filas["cuotas"][-n:]):
        estado_acuerdo = "cumplido"
    lotes.agregar("acuerdos_pago", {"id": acuerdo_id, "organizacion_id": org, "cobranza_id": cob["id"],
                                    "fecha_acuerdo": fecha_acuerdo, "monto_total_acordado": total, "pie": Decimal(0),
                                    "numero_cuotas": n, "dia_pago": primera.day, "fecha_primera_cuota": primera,
                                    "fecha_termino": primera + timedelta(days=30 * (n - 1)), "capital": capital,
                                    "honorarios": total - capital, "estado": estado_acuerdo, "usuario_id": usuario,
                                    "created_at": _ts(fecha_acuerdo, r)})
    lotes.agregar("gestiones", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                "usuario_id": usuario, "fecha_gestion": _ts(fecha_acuerdo, r),
                                "tipo_id": tipos_gestion.get("acuerdo"),
                                "descripcion": f"ACUERDO DE PAGO: ${int(total):,} en {n} cuotas.".replace(",", "."),
                                "created_at": _ts(fecha_acuerdo, r)})
    cob["monto_actual"] = max(Decimal(0), capital - pagado_capital)
    if estado_acuerdo == "cumplido" or cob["monto_actual"] == 0:
        cob["estado"], cob["motivo_cierre"] = "pagada", "pagada"
        cob["fecha_cierre"] = max(p["fecha_pago"] for p in lotes.filas["pagos"] if p["cobranza_id"] == cob["id"])
    elif estado_acuerdo == "vigente":
        cob["estado"] = "acuerdo_pago"


def _simular_abonos(r, lotes, org, cob, usuario, tipos_gestion, hoy) -> None:
    saldo = Decimal(cob["monto_actual"])
    fecha = cob["fecha_ingreso"]
    for _ in range(r.randint(1, 4)):
        fecha = fecha + timedelta(days=r.randint(15, 90))
        if fecha > hoy or saldo <= 0:
            break
        monto = min(saldo, Decimal(int(saldo * Decimal(r.choice([0.2, 0.3, 0.5, 1.0])) // 1000 * 1000) or saldo))
        saldo -= monto
        lotes.agregar("pagos", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                "fecha_pago": fecha, "monto": monto, "capital": monto, "honorarios": Decimal(0),
                                "intereses": Decimal(0), "gastos_judiciales": Decimal(0),
                                "forma_pago": _elegir(r, FORMAS), "estado_pago": "abono", "usuario_id": usuario,
                                "created_at": _ts(fecha, r)})
        lotes.agregar("gestiones", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                    "usuario_id": usuario, "fecha_gestion": _ts(fecha, r),
                                    "tipo_id": tipos_gestion.get("abono"),
                                    "descripcion": f"ABONO: ${int(monto):,}.".replace(",", "."),
                                    "created_at": _ts(fecha, r)})
    cob["monto_actual"] = saldo
    if saldo == 0:
        cob["estado"], cob["motivo_cierre"], cob["fecha_cierre"] = "pagada", "pagada", fecha


_ROLES: dict = {}


def _rol(anio: int) -> str:
    """Rol correlativo por año (nunca se repite en el mismo tribunal)."""
    _ROLES[anio] = _ROLES.get(anio, 1000) + 1
    return f"C-{_ROLES[anio]}-{anio}"


def _simular_causa(r, lotes, org, cob, deudor, cat, por_codigo, tribunales, abogados, procuradores,
                   admin, tipos_gestion, hoy, gastos_por_cliente) -> None:
    from app.judicial import TRAMITE_INICIAL, TRAMITE_INICIAL_DEFECTO

    fecha_demanda = cob["fecha_ingreso"] + timedelta(days=r.randint(90, 200))
    if fecha_demanda >= hoy:
        fecha_demanda = hoy - timedelta(days=r.randint(1, 10))
    procedimiento = _elegir(r, PROCEDIMIENTO_DOC[cob["tipo_documento"]])
    abogado, procurador = r.choice(abogados), r.choice(procuradores)
    causa_id = str(uuid.uuid4())
    causa = {"id": causa_id, "organizacion_id": org, "cliente_id": cob["cliente_id"], "deudor_id": deudor["id"],
             "rol": _rol(fecha_demanda.year), "tribunal_id": r.choice(tribunales),
             "procedimiento": procedimiento, "etapa_procesal": "demanda", "estado": "vigente", "resultado": None,
             "fecha_ingreso": fecha_demanda, "fecha_termino": None, "cuantia": cob["monto_actual"],
             "caratula": f"Mandante con {deudor['nombre']}"[:250], "abogado_id": abogado,
             "procurador_id": procurador, "creado_por": abogado, "created_at": _ts(fecha_demanda, r)}
    lotes.agregar("causas", causa)
    lotes.agregar("causa_cobranzas", {"organizacion_id": org, "causa_id": causa_id, "cobranza_id": cob["id"]})
    cob.update(estado="judicial", tipo="judicial", etapa="judicial", etapa_desde=fecha_demanda,
               fecha_traspaso=fecha_demanda)
    lotes.agregar("cambios_etapa", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                    "etapa_anterior": "extrajudicial", "etapa_nueva": "judicial", "usuario_id": abogado,
                                    "motivo": f"Demanda presentada rol {causa['rol']}", "created_at": _ts(fecha_demanda, r)})
    lotes.agregar("gestiones", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                "usuario_id": abogado, "fecha_gestion": _ts(fecha_demanda, r),
                                "tipo_id": tipos_gestion.get("demanda"),
                                "descripcion": f"DEMANDA PRESENTADA: rol {causa['rol']}.",
                                "created_at": _ts(fecha_demanda, r)})

    # Trámites siguiendo el flujo del catálogo, con observaciones entremedio.
    actual = por_codigo[TRAMITE_INICIAL.get(procedimiento, TRAMITE_INICIAL_DEFECTO)]
    fecha = fecha_demanda
    terminar = r.random() < min(0.9, (hoy - fecha_demanda).days / 900)
    pasos = r.randint(4, 14) if terminar else r.randint(2, 12)
    ultimo_tipo = None
    for paso in range(pasos):
        if fecha > hoy:
            break
        tid, codigo, etapa, plazo, siguiente, genera_gasto, _res = actual
        plazo_fecha = fecha + timedelta(days=plazo) if plazo is not None else None
        tramite_id = str(uuid.uuid4())
        lotes.agregar("tramites", {"id": tramite_id, "organizacion_id": org, "causa_id": causa_id, "tipo_id": tid,
                                   "fecha": fecha, "descripcion": None, "plazo_fecha": plazo_fecha,
                                   "siguiente_id": siguiente, "usuario_id": procurador, "created_at": _ts(fecha, r)})
        ultimo_tipo = actual
        if etapa:
            causa["etapa_procesal"] = etapa
        if genera_gasto and r.random() < 0.7:
            gasto = {"id": str(uuid.uuid4()), "organizacion_id": org, "cliente_id": cob["cliente_id"],
                     "causa_id": causa_id, "tramite_id": tramite_id, "fecha": fecha,
                     "tipo": "receptor" if etapa in ("notificacion", "embargo") else "otro",
                     "concepto": "Diligencia: " + codigo.replace("_", " "), "monto": _clp(r, 22_000, 0.5, 4000),
                     "proveedor": f"Receptor {r.choice(APELLIDOS)}", "numero_boleta": str(r.randint(100, 99999)),
                     "estado": "por_rendir", "usuario_id": procurador, "created_at": _ts(fecha, r)}
            lotes.agregar("gastos", gasto)
            gastos_por_cliente.setdefault(cob["cliente_id"], []).append(gasto)
        if etapa == "embargo" and codigo.startswith("embargo") and r.random() < 0.6:
            lotes.agregar("embargos", {"id": str(uuid.uuid4()), "organizacion_id": org, "causa_id": causa_id,
                                       "tipo_bien": _elegir(r, TIPOS_BIEN), "descripcion": "Bienes trabados (simulado)",
                                       "estado": r.choice(["trabado", "trabado", "retirado", "rematado", "alzado"]),
                                       "fecha_traba": fecha, "creado_por": procurador, "created_at": _ts(fecha, r)})
        for _ in range(r.choice([0, 1, 1, 2, 3, 4, 6])):
            obs = fecha + timedelta(days=r.randint(1, max(2, plazo or 20)))
            if obs <= hoy:
                lotes.agregar("tramites", {"id": str(uuid.uuid4()), "organizacion_id": org, "causa_id": causa_id,
                                           "tipo_id": None, "fecha": obs, "descripcion": r.choice(OBSERVACIONES_JUD),
                                           "usuario_id": procurador, "created_at": _ts(obs, r)})
        # Siguiente trámite: el sugerido por el catálogo o, si no hay, otro de la misma etapa.
        if siguiente and siguiente in cat:
            actual = cat[siguiente]
        else:
            misma = [t for t in cat.values() if t[2] == (etapa or causa["etapa_procesal"]) and t[0] != tid]
            if not misma:
                break
            actual = r.choice(misma)
        fecha = fecha + timedelta(days=int((plazo or r.randint(10, 40)) * r.uniform(0.6, 1.8)))

    if terminar and fecha <= hoy:
        resultado = _elegir(r, RESULTADO_CAUSA)
        causa.update(estado="terminada", resultado=resultado, fecha_termino=min(hoy, fecha))
        lotes.agregar("tramites", {"id": str(uuid.uuid4()), "organizacion_id": org, "causa_id": causa_id,
                                   "tipo_id": None, "fecha": causa["fecha_termino"],
                                   "descripcion": f"CAUSA TERMINADA: {resultado}.", "usuario_id": abogado,
                                   "created_at": _ts(causa["fecha_termino"], r)})
        estado, motivo = {"pagada": ("pagada", "pagada"), "avenimiento_cumplido": ("pagada", "avenimiento_cumplido"),
                          "castigo": ("castigo", _elegir(r, MOTIVO_CASTIGO)), "archivada": ("archivada", "otro"),
                          "desistida": ("archivada", "desistida")}[resultado]
        cob.update(estado=estado, motivo_cierre=motivo, fecha_cierre=causa["fecha_termino"])
        if estado == "pagada":
            lotes.agregar("pagos", {"id": str(uuid.uuid4()), "organizacion_id": org, "cobranza_id": cob["id"],
                                    "fecha_pago": causa["fecha_termino"], "monto": cob["monto_actual"],
                                    "capital": cob["monto_actual"], "honorarios": Decimal(0), "intereses": Decimal(0),
                                    "gastos_judiciales": Decimal(0), "forma_pago": "deposito", "estado_pago": "pagado",
                                    "usuario_id": admin, "created_at": _ts(causa["fecha_termino"], r)})
            cob["monto_actual"] = Decimal(0)
    _ = ultimo_tipo


def _rendir_gastos(r, lotes, org, gastos_por_cliente, admin, hoy) -> None:
    """Los gastos viejos se rinden mes a mes por cliente; los más viejos ya los devolvió el cliente."""
    numero = 0
    for cliente_id, gastos in gastos_por_cliente.items():
        por_mes: dict[tuple, list] = {}
        for g in gastos:
            if (hoy - g["fecha"]).days > 45:
                por_mes.setdefault((g["fecha"].year, g["fecha"].month), []).append(g)
        for (anio, mes), lista in sorted(por_mes.items()):
            numero += 1
            fecha = date(anio, mes, 28) + timedelta(days=5)
            pagada = (hoy - fecha).days > 60 or r.random() < 0.5
            rid = str(uuid.uuid4())
            lotes.agregar("rendiciones_gastos", {
                "id": rid, "organizacion_id": org, "numero": numero, "cliente_id": cliente_id, "fecha": min(fecha, hoy),
                "total": sum((g["monto"] for g in lista), Decimal(0)), "estado": "pagada" if pagada else "enviada",
                "fecha_pago": min(hoy, fecha + timedelta(days=r.randint(10, 50))) if pagada else None,
                "creado_por": admin, "created_at": _ts(min(fecha, hoy), r)})
            for g in lista:
                g["rendicion_id"] = rid
                g["estado"] = "reembolsado" if pagada else "rendido"
                g["fecha_reembolso"] = min(hoy, fecha + timedelta(days=30)) if pagada else None


# ------------------------------------------------------------------ medición

PRUEBAS = [
    ("Cobranzas: primera página", "GET", "/api/cobranzas/?limit=20", None),
    ("Cobranzas: filtro por etapa judicial", "GET", "/api/cobranzas/?etapa=judicial&limit=20", None),
    ("Buscar cobranza por apellido", "GET", "/api/cobranzas/buscar?q=Gonz", None),
    ("Buscar deudor", "GET", "/api/deudores/buscar?q=Rojas&limit=30", None),
    ("Ficha de cobranza", "GET", "/api/cobranzas/{cobranza}", None),
    ("Historial de gestiones", "GET", "/api/gestiones/?cobranza_id={cobranza}", None),
    ("Barra del ciclo de vida", "GET", "/api/cobranzas/{cobranza}/ciclo", None),
    ("Pagos de la cobranza", "GET", "/api/pagos/?cobranza_id={cobranza}", None),
    ("Avisos (campana)", "GET", "/api/agenda/avisos", None),
    ("Agenda del mes (todo el equipo)", "GET", "/api/agenda?todos=true", None),
    ("Panel de indicadores", "GET", "/api/panel", None),
    ("Judicial: resumen de la bandeja", "GET", "/api/judicial/resumen", None),
    ("Judicial: causas vigentes", "GET", "/api/judicial/causas?limit=25", None),
    ("Judicial: plazos vencidos", "GET", "/api/judicial/causas?plazo=vencido&limit=25", None),
    ("Judicial: ficha de causa", "GET", "/api/judicial/causas/{causa}", None),
    ("Judicial: para demandar", "GET", "/api/judicial/para-demanda", None),
    ("Gastos: resumen por cliente", "GET", "/api/gastos/resumen", None),
    ("Gastos por rendir", "GET", "/api/gastos/?estado=por_rendir&limit=200", None),
    ("Registrar una gestión", "POST", "/api/gestiones/", "gestion"),
]


def medir(cliente_http, email: str, password: str, repeticiones: int = 5, informar=print) -> list[dict]:
    """Mide los tiempos de respuesta de las pantallas principales (en el servidor, sin red)."""
    r = cliente_http.post("/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        raise SystemExit(f"No se pudo entrar como {email}: {r.text}")
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    cobranza = cliente_http.get("/api/cobranzas/?etapa=judicial&limit=1", headers=h).json()[0]["id"]
    causas = cliente_http.get("/api/judicial/causas?limit=1", headers=h).json()
    causa = causas[0]["id"] if causas else None
    resultados = []
    for nombre, metodo, ruta, cuerpo in PRUEBAS:
        if "{causa}" in ruta and not causa:
            continue
        url = ruta.format(cobranza=cobranza, causa=causa)
        tiempos = []
        estado = 0
        for _ in range(repeticiones):
            t0 = time.perf_counter()
            if metodo == "GET":
                resp = cliente_http.get(url, headers=h)
            else:
                resp = cliente_http.post(url, headers=h, json={"cobranza_id": cobranza,
                                                               "descripcion": "Gestión de prueba de rendimiento"})
            tiempos.append((time.perf_counter() - t0) * 1000)
            estado = resp.status_code
        fila = {"prueba": nombre, "estado": estado, "mediana_ms": round(statistics.median(tiempos)),
                "max_ms": round(max(tiempos))}
        resultados.append(fila)
        informar(f"  {nombre:<40} {fila['mediana_ms']:>6} ms  (máx {fila['max_ms']:>5} ms)  HTTP {estado}")
    return resultados
