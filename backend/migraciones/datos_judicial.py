"""
Catálogo de trámites judiciales de sistema que siembra la migración 0010.

Sale del flujo procesal que usaban los estudios en su sistema anterior: para
cada trámite, cuántos días esperar antes de revisar (plazo de seguimiento),
qué trámite suele venir después, si genera gasto (receptor, conservador,
publicación...) y si es una alerta importante. Se limpió de duplicados y se
dejaron nombres genéricos.

Los plazos son de SEGUIMIENTO en días corridos ("revisar en N días"), no el
cómputo legal en días hábiles. Los plazos legales críticos van en la nota.
Cada organización puede crear sus propios trámites o ajustar los suyos.

Esta lista queda congelada con la migración: los cambios posteriores van en
una migración nueva.

Columnas: (codigo, nombre, etapa, plazo_dias, siguiente, genera_gasto,
           alerta, nota, resultado)

  etapa     → demanda / notificacion / embargo / defensa / remate, o None si
              el trámite no mueve la causa de etapa.
  resultado → si el trámite normalmente cierra la causa (el sistema propone
              terminarla): pagada / avenimiento_cumplido / castigo /
              desistida / abandono / prescrita / archivada.
"""

TRAMITES = [
    # ---------------------------------------------------------------- Demanda
    ("demanda_presentada", "Se presenta demanda y documentos al tribunal", "demanda", 10, "distribucion_rol", False, False, None, None),
    ("distribucion_rol", "Distribución e ingreso de rol", "demanda", 5, "acompana_documentos", False, False, "Anotar el rol y el tribunal en la causa.", None),
    ("acompana_documentos", "Acompaña documentos y custodia del título", "demanda", 5, "mandamiento", False, False, None, None),
    ("patrocinio_poder", "Constituye patrocinio y poder", "demanda", None, None, False, False, None, None),
    ("rectifica_demanda", "Escrito rectifica la demanda", "demanda", 2, "encarga_notificacion", False, False, None, None),
    ("mandamiento", "Encargado mandamiento de ejecución y embargo", "demanda", 10, "encarga_notificacion", True, False, None, None),
    ("demanda_ejecutiva", "Se presenta demanda ejecutiva (tras la gestión preparatoria)", "demanda", 5, "mandamiento", False, False, None, None),
    ("tengase_presente", "Escrito téngase presente", None, None, None, False, False, None, None),
    ("exhorto", "Se solicita exhorto a otro tribunal", "demanda", 30, None, True, False, "Anotar tribunal exhortado y rol del exhorto.", None),

    # ---------------------------------------------------------- Notificación
    ("encarga_notificacion", "Encarga notificación al receptor", "notificacion", 30, "notificado_requerido", True, False, None, None),
    ("busqueda_positiva", "Búsqueda positiva: el deudor vive en el domicilio", "notificacion", 10, "pide_art44", True, False, "Conseguir copia del estampado del receptor.", None),
    ("busqueda_negativa", "Búsqueda negativa", "notificacion", 10, "nuevo_domicilio", True, False, None, None),
    ("pide_art44", "Se pide notificación por artículo 44", "notificacion", 20, "notificado_art44", False, False, None, None),
    ("notificado_requerido", "Notificado y requerido de pago", "notificacion", 10, "certificado_no_excepciones", True, True,
     "Plazo para oponer excepciones: 4 días hábiles (8 si se notificó fuera de la comuna del tribunal). Revisar si se opusieron.", None),
    ("notificado_art44", "Notificado por artículo 44", "notificacion", 10, "certificado_no_excepciones", True, True,
     "Plazo para oponer excepciones corre desde la notificación. Revisar si se opusieron.", None),
    ("notificado_cedula", "Notificado por cédula", "notificacion", None, None, True, False, None, None),
    ("notificado_art52", "Notificado por artículo 52", "notificacion", None, None, True, False, None, None),
    ("nuevo_domicilio", "Señala nuevo domicilio", "notificacion", 2, "encarga_notificacion", False, False, None, None),
    ("deudor_cambio_domicilio", "Deudor se cambió de domicilio", "notificacion", 15, "nuevo_domicilio", False, False, None, None),
    ("reitera_receptor", "Se reitera el encargo al receptor", None, 15, None, False, False, "Apurar la diligencia encargada.", None),
    ("receptor_inubicable", "Receptor certifica que el deudor es inubicable", "notificacion", 10, "certificado_castigo", True, False, None, None),
    ("domicilio_inexistente", "Receptor certifica domicilio inexistente", "notificacion", 10, "nuevo_domicilio", True, False, None, None),
    # Gestiones preparatorias de la vía ejecutiva
    ("notificado_protesto_cheque", "Notificado el protesto de cheque", "notificacion", 10, "certificado_cheque", True, True,
     "Plazo de 3 días para tachar de falsa la firma o consignar. Verificar incidentes de nulidad.", None),
    ("notificado_protesto_letra", "Notificado el protesto de letra o pagaré", "notificacion", 10, "certificado_no_tacha", True, False, None, None),
    ("notificada_factura", "Notificada la factura", "notificacion", 10, "certificado_no_tacha", True, False,
     "Plazo de 3 días para alegar falsificación o falta de entrega.", None),
    ("citacion_confesar", "Se presenta citación a confesar deuda o reconocer firma", "demanda", 10, "notificada_confesion", False, False, None, None),
    ("notificada_confesion", "Notificada la citación a confesar deuda o reconocer firma", "notificacion", 3, "audiencia_confesion", True, True,
     "Anotar fecha y hora de la audiencia.", None),
    ("notificada_demanda_ordinaria", "Notificada la demanda en juicio ordinario", "notificacion", 15, "contestacion", True, False,
     "Si el demandado no contesta, evacuar en rebeldía.", None),

    # ------------------------------------------- Excepciones, prueba y sentencia
    ("certificado_no_excepciones", "Certificado: no opuso excepciones", "defensa", 15, "embargo_bienes", False, False, None, None),
    ("opone_excepciones", "El ejecutado opone excepciones", "defensa", 4, "contesta_excepciones", False, True,
     "Informar al abogado: hay plazo para contestar el traslado.", None),
    ("contesta_excepciones", "Contesta traslado de excepciones", "defensa", 10, "recibe_prueba", False, False, None, None),
    ("rechazo_excepciones", "Se rechazan las excepciones", "defensa", 10, "embargo_bienes", False, False, None, None),
    ("certificado_cheque", "Certificado de secretaría: no pagó ni tachó (cheque)", "defensa", 10, "demanda_ejecutiva", False, False,
     "Con el certificado queda preparada la vía ejecutiva. Evaluar compulsas al crimen.", None),
    ("certificado_no_tacha", "Certificado: no opuso tacha de falsedad", "defensa", 20, "demanda_ejecutiva", False, False, None, None),
    ("audiencia_confesion", "Audiencia de confesión de deuda", "defensa", 5, "confeso_deuda", False, True, "El abogado o procurador debe concurrir.", None),
    ("confeso_deuda", "Deudor reconoce la deuda o firma, o no comparece", "defensa", 5, "certificado_confeso", False, False, None, None),
    ("niega_deuda", "Deudor comparece y niega la deuda", "defensa", 5, None, False, True, "Evaluar juicio ordinario con el abogado.", None),
    ("certificado_confeso", "Certificado: se le tiene por confeso", "defensa", 30, "demanda_ejecutiva", False, False, None, None),
    ("contestacion", "El demandado contesta la demanda", "defensa", 7, "replica", False, False, None, None),
    ("rebeldia", "Se evacúa el traslado en rebeldía", "defensa", 15, "replica", False, False, None, None),
    ("replica", "Se presenta réplica", "defensa", 10, "duplica", False, False, None, None),
    ("duplica", "Se presenta dúplica", "defensa", 5, "conciliacion", False, False, None, None),
    ("conciliacion", "Se cita a audiencia de conciliación", "defensa", 30, "recibe_prueba", False, True, "Informar si se realizó la audiencia.", None),
    ("recibe_prueba", "Se recibe la causa a prueba", "defensa", 10, "notificado_auto_prueba", False, False, None, None),
    ("notificado_auto_prueba", "Notificado el auto de prueba", "defensa", 15, "rinde_prueba", True, False, None, None),
    ("lista_testigos", "Se presenta lista de testigos", "defensa", 20, "rinde_prueba", False, True, "El abogado debe concurrir a la audiencia.", None),
    ("rinde_prueba", "Se rinde la prueba", "defensa", 15, "vencimiento_probatorio", False, False, None, None),
    ("vencimiento_probatorio", "Certificado de vencimiento del probatorio", "defensa", 20, "citacion_sentencia", False, False, None, None),
    ("citacion_sentencia", "Se cita a las partes a oír sentencia", "defensa", 30, "sentencia", False, False, "Revisar cada 30 días si salió la sentencia.", None),
    ("sentencia", "Se dicta sentencia", "defensa", 10, "notifica_sentencia", False, True, "Revisar si es favorable y si conviene apelar.", None),
    ("notifica_sentencia", "Notificada la sentencia", "defensa", 10, None, True, False, None, None),
    ("apelacion", "Se interpone apelación", "defensa", 5, "eleva_corte", False, True, None, None),
    ("eleva_corte", "El expediente se eleva a la Corte", "defensa", 30, None, False, False, "Hacerse parte en la Corte.", None),
    ("incidente_nulidad", "Incidente de nulidad", "defensa", 3, "contesta_incidente", False, True, "Informar al abogado.", None),
    ("contesta_incidente", "Contesta traslado del incidente", "defensa", 20, None, False, False, "Revisar cada 30 días si se resolvió.", None),
    ("acoge_incidente", "Se acoge el incidente", "defensa", 15, None, False, True, "Estudiar el caso con el abogado.", None),
    ("rechaza_incidente", "Se rechaza el incidente", "defensa", 20, None, False, False, None, None),
    ("terceria", "Se interpone tercería", "defensa", 3, "contesta_terceria", False, True, "Informar al abogado.", None),
    ("contesta_terceria", "Contesta traslado de la tercería", "defensa", 20, "resuelve_terceria", False, False, None, None),
    ("resuelve_terceria", "Se resuelve la tercería", "defensa", 20, None, False, True, "Indicar si se acoge o se rechaza.", None),

    # ---------------------------------------------------------------- Embargo
    ("embargo_bienes", "Se embargan bienes muebles", "embargo", 15, "designacion_martillero", True, False, "Registrar el embargo en la pestaña Embargos.", None),
    ("embargo_vehiculo", "Se embarga vehículo", "embargo", 15, "designacion_martillero", True, False, "Inscribir en el Registro de Vehículos Motorizados.", None),
    ("embargo_inmueble", "Se embarga inmueble", "embargo", 10, "inscripcion_conservador", True, False, None, None),
    ("retencion_fondos", "Retención de fondos en cuenta bancaria", "embargo", 15, "giro_cheque", True, False, None, None),
    ("inscripcion_conservador", "Inscripción del embargo en el Conservador de Bienes Raíces", "embargo", 20, "tasacion_inmueble", True, False, None, None),
    ("embargo_frustrado", "Embargo frustrado: no se encontraron bienes", "embargo", 10, "certificado_castigo", True, False, None, None),
    ("pide_fuerza_publica", "Se pide auxilio de la fuerza pública", "embargo", 2, "encarga_fuerza_publica", False, False, None, None),
    ("encarga_fuerza_publica", "Encarga al receptor diligencia con fuerza pública", "embargo", 30, "embargo_bienes", True, True, "Verificar que se trabó el embargo.", None),
    ("oposicion_embargo", "Oposición al embargo", "embargo", 15, None, False, True, "Informar al abogado.", None),
    ("ampliacion_embargo", "Se pide ampliación del embargo", "embargo", 10, "encarga_notificacion", False, False, None, None),
    ("retiro_especies", "Se retiran las especies embargadas", "embargo", 10, "designacion_martillero", True, False, None, None),
    ("retiro_frustrado", "Retiro frustrado: no estaban los bienes", "embargo", 10, None, True, False, None, None),
    ("oposicion_retiro", "Oposición al retiro", "embargo", 10, None, False, False, None, None),
    ("alzamiento_embargo", "Alzamiento del embargo", "embargo", None, None, False, False, "Actualizar el estado del embargo.", None),

    # ------------------------------------------------------- Remate y pago
    ("designacion_martillero", "Designación de martillero", "remate", 10, "notifica_martillero", False, False, None, None),
    ("notifica_martillero", "Se notifica al martillero", "remate", 15, "fecha_remate", True, True, "Consultar al martillero la fecha del remate.", None),
    ("tasacion_inmueble", "Se propone tasación del inmueble", "remate", 20, "bases_remate", False, False, None, None),
    ("bases_remate", "Bases de remate", "remate", 20, "publicacion_remate", False, False, None, None),
    ("publicacion_remate", "Publicación del remate en el diario", "remate", 15, "fecha_remate", True, False, None, None),
    ("fecha_remate", "Se fija fecha de remate", "remate", 30, "consignacion_remate", True, True, "Registrar el monto del remate.", None),
    ("consignacion_remate", "Se consigna el valor del remate", "remate", 10, "liquidacion_credito", False, False, "Si queda saldo, pedir ampliación del embargo.", None),
    ("rendicion_martillero", "Oficio al martillero para que rinda cuenta", "remate", 15, None, True, False, None, None),
    ("consignacion_deudor", "El deudor consigna en el tribunal", "remate", 10, "giro_cheque", False, False, None, None),
    ("liquidacion_credito", "Se solicita liquidación del crédito", "remate", 30, "giro_cheque", False, True, "Verificar la liquidación del crédito.", None),
    ("giro_cheque", "Se solicita giro de cheque", "remate", 20, "retira_cheque", False, False, None, None),
    ("retira_cheque", "Se retira el cheque del tribunal", "remate", 1, "da_cuenta_pago", False, False, "Registrar el pago en la cobranza.", None),

    # ---------------------------------------------------------------- Término
    ("da_cuenta_pago", "Se da cuenta de pago en el tribunal", None, None, None, False, False, None, "pagada"),
    ("avenimiento", "Avenimiento judicial", None, 90, None, False, False, "Revisar el cumplimiento cada 90 días.", None),
    ("cumplimiento_avenimiento", "Se pide el cumplimiento del avenimiento", None, 30, None, False, True, None, None),
    ("avenimiento_cumplido", "Avenimiento cumplido", None, None, None, False, False, None, "avenimiento_cumplido"),
    ("desistimiento", "Desistimiento de la demanda", None, None, None, False, False, None, "desistida"),
    ("abandono", "Abandono del procedimiento", None, None, None, False, True, "Informar al abogado.", "abandono"),
    ("prescripcion", "Acción prescrita", None, None, None, False, True, "Daño al cliente: informar de inmediato.", "prescrita"),
    ("deudor_sin_bienes", "Deudor no tiene bienes embargables", None, 10, "certificado_castigo", False, False, None, None),
    ("deudor_fallecido", "Deudor fallecido", None, 10, "certificado_castigo", False, False, None, None),
    ("deudor_liquidacion", "Deudor en procedimiento de liquidación (quiebra)", None, 15, "verificacion_credito", False, True, None, None),
    ("verificacion_credito", "Se verifica el crédito en la liquidación", None, 60, None, False, False, None, None),
    ("certificado_castigo", "Se solicita certificado para castigo", None, 20, "carta_castigo", True, False, None, None),
    ("carta_castigo", "Carta de castigo al cliente", None, None, None, False, False, None, "castigo"),
    ("causa_archivada", "Causa archivada", None, None, None, False, False, None, "archivada"),
    ("desarchivo", "Se solicita desarchivo de la causa", None, 10, None, True, False, None, None),
    ("suspendida_cliente", "Suspendida por instrucción del cliente", None, 30, None, False, False, None, None),
    ("acumula_causa", "Se acumula a otra causa", None, None, None, False, False, "Anotar el rol de la causa a la que se acumula.", None),
    ("expediente_extraviado", "Expediente extraviado", None, 10, "reconstitucion", False, True, "Informar al abogado.", None),
    ("reconstitucion", "Se solicita reconstituir el expediente", None, 30, None, False, True, "Pedir instrucciones al abogado.", None),

    # ---------------------------------------------------------------- Querella
    ("compulsas", "Se encargan y pagan compulsas", "demanda", 5, "envio_compulsas", True, True, "Anotar el juzgado y el rol de la causa penal.", None),
    ("envio_compulsas", "Se envían las compulsas al tribunal penal", "demanda", 10, "querella", False, False, "Remitir copia al cliente.", None),
    ("querella", "Se presenta querella", "demanda", 20, "formalizacion", False, False, None, None),
    ("formalizacion", "Formalización o auto de procesamiento", "defensa", 90, None, False, True, "Verificar el estado de la causa.", None),
    ("orden_detencion", "Orden de detención pendiente", "defensa", 60, None, False, False, None, None),
    ("sentencia_penal", "Sentencia en la causa penal", "defensa", 10, None, False, True, None, None),
    ("sobreseimiento", "Sobreseimiento de la causa penal", None, 10, None, False, False, "Indicar la fecha de sobreseimiento y archivo.", "archivada"),
]


def _civiles(ciudad: str, n: int, tipo: str = "Civil") -> list:
    return [(f"{i}° Juzgado {tipo} de {ciudad}", ciudad, "civil") for i in range(1, n + 1)]


# Tribunales de sistema (públicos). Cada organización agrega los que le falten.
# Columnas: (nombre, ciudad, competencia)
TRIBUNALES = (
    _civiles("Valparaíso", 5)
    + _civiles("Viña del Mar", 3)
    + _civiles("Quilpué", 2)
    + [("Juzgado de Letras de Villa Alemana", "Villa Alemana", "civil"),
       ("Juzgado de Letras de Limache", "Limache", "civil"),
       ("Juzgado de Letras de La Calera", "La Calera", "civil"),
       ("Juzgado de Letras de Casablanca", "Casablanca", "civil"),
       ("Juzgado de Letras de Quintero", "Quintero", "civil"),
       ("Juzgado de Letras de La Ligua", "La Ligua", "civil")]
    + _civiles("Quillota", 2, "de Letras")
    + _civiles("San Felipe", 2, "de Letras")
    + _civiles("Los Andes", 2, "de Letras")
    + _civiles("San Antonio", 2, "de Letras")
    + _civiles("Santiago", 30)
    + _civiles("La Serena", 3, "de Letras")
    + _civiles("Coquimbo", 3, "de Letras")
    + [("Juzgado de Garantía de Valparaíso", "Valparaíso", "penal"),
       ("Juzgado de Garantía de Viña del Mar", "Viña del Mar", "penal"),
       ("Corte de Apelaciones de Valparaíso", "Valparaíso", "corte"),
       ("Corte de Apelaciones de Santiago", "Santiago", "corte")]
)
