"""
Motor de completitud (MVP) para los campos que extrae extract_solicitud.py
(todos los Bloques, 0 a 14). Marca qué campos vinieron vacíos y deberían
estar cargados.

QUÉ SABE Y QUÉ NO (ver conversación con Bells Group sobre este punto):
No existe una hoja "Reglas_Validacion" en la Base_Combinada, ni una
definición de "campos obligatorios por producto" (Options 1 vida / 2
vidas / Invest Future / Invest Future Joven / Invest Future - Tomador
distinto). Con 5 solicitudes de ejemplo repartidas en 4 productos
distintos (alguno con un solo caso) no alcanza para inferir esa regla de
forma confiable -- así que este motor NO diferencia por esas variantes.

Lo único que se puede diferenciar de forma 100% literal es la familia
"Zurich Options" vs "Zurich Invest Future" (ver "Producto / Formulario"
en extract_bloque_0) -- las variantes más finas ("Vida Única"/"Dos
Vidas", "Joven", "Tomador distinto") no siempre están tipeadas en el PDF.
Esa familia SÍ cambia qué se chequea a partir del Bloque 6: "Enfermedad
Grave", "Renta Familiar" y "Pérdida de Miembros" son EXCLUSIVOS de
Options (no tienen equivalente en el Bloque 6c de Invest Future);
"Hospitalización", "Muerte Accidental", "Invalidez Total y Permanente" y
"Exención de Pago de Primas" en cambio son comunes a ambas familias
(mismo caption, mismo campo, Bloque 6 o 6c según corresponda) y se
chequean sin filtrar por familia. "Seguro de Vida Adicional" es un caso
mixto: el Monto es común a ambas, pero el checkbox Sí/No que lo habilita
SOLO existe en Invest Future (en Options no hay Sí/No, el monto es
siempre obligatorio) -- por eso el condicional que lo habilita está
restringido a esa familia (ver _CONDICIONALES). Al revés en el Bloque 7:
"Pago en adición a Cuenta Individual", "Estrategia Predeterminada" y los
6 "Asignación Zurich X %" son exclusivos de Invest Future (confirmado
contra Base_Combinada) y solo se piden si el producto es Invest Future;
"Cuenta Individual - Pesos/Dólares" en cambio es común a ambas familias.
Los 6 campos de asignación de fondos, además, solo se piden si
"Estrategia Predeterminada" quedó en "No" (si es "Sí" no hay tabla manual
que completar). Mismo patrón en el Bloque 8: "Póliza Vanishing" y
"Actualización de Primas y Beneficios" son de Options; "Incremento anual
automático" (con su nivel y plazo) y "Vida decreciente" (Bloque 6c) son
de Invest Future. "Declaración de Salud 'conforme'/'no conforme'" (Bloque
12) también es exclusivo de Invest Future -- confirmado contra
Base_Combinada (viene "N/A" en las Options de prueba).

"Vacío legítimo" (de la hoja Leyenda de la Base_Combinada + lo observado
en los 5 ejemplos reales): Piso, Departamento, Tel. celular y todo el
domicilio de correspondencia son opcionales siempre. El detalle de
actividad peligrosa, el detalle de tabaco y los datos de viaje al
exterior son opcionales SALVO que la pregunta Sí/No correspondiente haya
sido contestada "Sí" -- ahí si vienen vacíos sí es información
incompleta de verdad. "PEP - Motivo detallado" es lo mismo pero para
"¿PEP?" (Bloque 12). Los campos que el extractor directamente no
calibró contra ningún ejemplo real (ver docstrings de extract_bloque_6,
extract_bloque_7 y extract_bloque_12) tampoco se chequean acá: pedirían
completitud a un campo que HOY el extractor nunca llena aunque el dato
sí exista en el PDF, lo que generaría un falso "incompleto" en cada
solicitud, no una detección real de un dato faltante.

BLOQUES 10/11 (Beneficiarios principales / contingentes): a diferencia
del resto, acá "vacío" NO es sinónimo de "incompleto" -- es normal tener
menos de 3 beneficiarios principales o 0 contingentes. Lo que sí se
chequea es consistencia POR FILA: si "Nombre" de un beneficiario vino
cargado, el resto de esa misma fila (Fecha de nacimiento, CUIL/CUIT,
Relación/%) debería estarlo también (ver _incompletos_fila). En
Contingentes, además, se chequea que se haya marcado la Opción A o la
Opción B -- confirmado contra Base_Combinada que 3 de los 5 ejemplos de
prueba SÍ tienen esto sin marcar ("(sin datos cargados)" en la
planilla), así que es una detección real, no falsa alarma.

Uso:
    from extract_solicitud import extract_solicitud
    from check_completitud import verificar_completitud
    campos = extract_solicitud(pdf_path)
    incompletos = verificar_completitud(campos)
"""

_PREFIJOS = [
    "SOLICITANTE / TOMADOR - ",
    "SOLICITANTE CONJUNTO - ",
    "VIDA ASEGURADA 1 - ",
    "VIDA ASEGURADA 2 - ",
]

# Si el campo centinela de una sección viene en None, toda la sección no
# existe en esta solicitud (no es que falte un dato, es que ese bloque no
# aplica -- ej. no hay Solicitante Conjunto en una póliza de 1 vida).
_CENTINELA_SECCION = {
    "SOLICITANTE CONJUNTO - ": "Sexo - Masculino",
    "VIDA ASEGURADA 2 - ": "Sexo - Masculino",
}

_SIEMPRE_OPCIONALES = {
    "Piso",
    "Departamento",
    "Tel. celular",
    "Correspondencia - Indique cuál",
    "Correspondencia - Calle",
    "Correspondencia - Número",
    "Correspondencia - Piso",
    "Correspondencia - Departamento",
    "Correspondencia - Localidad",
    "Correspondencia - Provincia",
    "Correspondencia - Código Postal",
    "Correspondencia - País",
    # Se chequean como grupo al final de verificar_completitud, no campo
    # por campo (ver _CAMPOS_ASIGNACION_FONDOS).
    "Asignación Zurich Money %",
    "Asignación Zurich Income / Income II %",
    "Asignación Zurich Performance %",
    "Asignación Zurich Commodities %",
    "Asignación Zurich Performance International II % (dólar)",
    "Asignación Zurich Performance Tech % (dólar)",
    # No calibrados contra ningún ejemplo real (ver docstring de
    # extract_bloque_12) -- en los 5 PDF de prueba esta tabla siempre
    # viene con "No disponible" pre-impreso, nunca un dato real tipeado.
    "Jurisdicción fiscal adicional",
    "Número identificación tributaria",
    # Ídem -- no implementados (ver docstring de extract_bloque_12: el
    # único ejemplo real de 2 vidas tiene esta fila partida en dos líneas
    # por pdf_layout, no alcanza para calibrar una heurística confiable).
    "Solicitante Conjunto - ¿Residencia fiscal fuera AR? - No",
    "Solicitante Conjunto - ¿Contribuyente EE.UU.? - No",
}

# (sufijo del campo dependiente, sufijo del checkbox "Sí" que lo habilita,
# familia requerida o None si aplica a ambas)
_CONDICIONALES = [
    ("Actividad peligrosa - Detalle", "Actividad peligrosa - Sí", None),
    ("Actividad peligrosa - Frecuencia", "Actividad peligrosa - Sí", None),
    ("Tabaco - Producto y cantidad diaria", "¿Fumador últimos 12 meses? - Sí", None),
    ("Exterior - País", "¿Visitar/residir/trabajar en otro país? - Sí", None),
    ("Exterior - Razón", "¿Visitar/residir/trabajar en otro país? - Sí", None),
    ("Exterior - Visitas al año", "¿Visitar/residir/trabajar en otro país? - Sí", None),
    ("Exterior - Plazo por visita", "¿Visitar/residir/trabajar en otro país? - Sí", None),
    ("Detalle otras solicitudes", "Otra solicitud últimos 6 meses - Sí", None),
    ("Detalle rechazo/reclamo", "Rechazo/condición especial - Sí", None),
    ("Enfermedad Grave - Monto", "Enfermedad Grave - Sí", None),
    ("Renta Familiar - Monto anual", "Renta Familiar - Sí", None),
    ("Renta Familiar - Años", "Renta Familiar - Sí", None),
    ("Muerte Accidental - Monto", "Muerte Accidental - Sí", None),
    ("Hospitalización - Monto", "Hospitalización - Sí", None),
    ("Invalidez Total y Permanente - Monto", "Invalidez Total y Permanente - Sí", None),
    ("Pérdida de Miembros - Monto", "Pérdida de Miembros - Sí", None),
    ("Póliza Vanishing - Años", "¿Póliza Vanishing? - Sí", None),
    ("Incremento anual - Plazo (años)", "Incremento anual automático - Sí", None),
    ("Plazo de pago de primas (años)", "Incremento anual automático - Sí", None),
    ("Tarjeta - Últimos 4 dígitos", "Medio de pago - Tarjeta de crédito", None),
    ("CBU - Últimos 4 dígitos", "Medio de pago - CBU", None),
    ("PEP - Motivo detallado", "¿PEP - Persona Expuesta Políticamente? - Sí", None),
    # "Seguro de Vida Adicional" y "Vida decreciente" (Bloque 6c) SOLO
    # tienen checkbox habilitante en Invest Future -- en Options el Monto
    # del Seguro de Vida Adicional es siempre obligatorio (no hay
    # Sí/No que lo condicione), así que este condicional no debe
    # aplicarse ahí.
    ("Seguro de Vida Adicional - Monto", "Seguro de Vida Adicional - Sí", "Zurich Invest Future"),
    ("Vida decreciente - Monto", "Vida decreciente - Sí", "Zurich Invest Future"),
]

# Los 6 fondos de "Asignación Zurich X %" no son todos obligatorios juntos
# cuando "Estrategia Predeterminada" es "No": el Solicitante reparte 100%
# entre LOS QUE QUIERA (ej. dos fondos al 75%/25%), así que casi siempre
# la mayoría de estos 6 campos van a quedar vacíos a propósito -- no se
# chequean campo por campo (ver _CONDICIONALES), sino como grupo más abajo.
_CAMPOS_ASIGNACION_FONDOS = [
    "Asignación Zurich Money %",
    "Asignación Zurich Income / Income II %",
    "Asignación Zurich Performance %",
    "Asignación Zurich Commodities %",
    "Asignación Zurich Performance International II % (dólar)",
    "Asignación Zurich Performance Tech % (dólar)",
]

# Campos de Bloque 0 que son derivados (todavía no extraídos por
# coordenadas, ver docstring de extract_solicitud.py) -- no se chequean
# acá como "incompletos", ya están señalados aparte como pendientes.
_DERIVADOS_BLOQUE_0 = {
    "Cantidad de vidas aseguradas",
    "Tomador distinto de la Vida Asegurada - Sí",
    "Tomador distinto de la Vida Asegurada - No",
    "Tipo de firma",
}

# Bloques 6/6c: "Enfermedad Grave", "Renta Familiar" y "Pérdida de
# Miembros" son EXCLUSIVOS de Options -- Invest Future no tiene un
# beneficio equivalente en su Bloque 6c (confirmado contra
# Base_Combinada y contra el propio PDF). Sin este filtro, toda
# solicitud Invest Future aparecería con estos campos "incompletos" por
# error (nunca van a tener dato).
_SUFIJOS_SOLO_OPTIONS = {
    suf
    for base in ("Enfermedad Grave", "Renta Familiar", "Pérdida de Miembros")
    for suf in (
        f"{base} - Sí", f"{base} - No", f"{base} - Monto",
        f"{base} - Monto anual", f"{base} - Años",
    )
} | {
    # Bloque 8: Vanishing / Actualización de Primas son exclusivos de
    # Options (confirmado contra Base_Combinada).
    "¿Póliza Vanishing? - Sí",
    "¿Póliza Vanishing? - No",
    "Póliza Vanishing - Años",
    "¿Actualización de Primas y Beneficios? - Sí",
    "¿Actualización de Primas y Beneficios? - No",
}

# Campos "sueltos" (sin prefijo) de los Bloques 6c/7/8/12/13/14
# exclusivos de Invest Future. "Cuenta Individual - Pesos/Dólares" y
# "Frecuencia de pago - ..." son de ambas familias; el resto es
# exclusivo de Invest Future (confirmado contra Base_Combinada: vienen
# "N/A" en las solicitudes Options de prueba).
_SUFIJOS_SOLO_INVEST_FUTURE = {
    # Bloque 6c, sin ambigüedad con Bloque 6 (no tienen equivalente
    # prefijado por Vida Asegurada -- ver _SUFIJOS_BENEFICIO_COMPARTIDO
    # para los 5 que sí lo tienen).
    "Pago en adición a Cuenta Individual - Sí",
    "Pago en adición a Cuenta Individual - No",
    "Vida decreciente - Sí",
    "Vida decreciente - No",
    "Vida decreciente - Monto",
    # Bloque 7
    "Estrategia Predeterminada - Sí",
    "Estrategia Predeterminada - No",
    "Asignación Zurich Money %",
    "Asignación Zurich Income / Income II %",
    "Asignación Zurich Performance %",
    "Asignación Zurich Commodities %",
    "Asignación Zurich Performance International II % (dólar)",
    "Asignación Zurich Performance Tech % (dólar)",
    # Bloque 8
    "Incremento anual automático - Sí",
    "Incremento anual automático - No",
    "Incremento anual - 5%",
    "Incremento anual - 10%",
    "Incremento anual - Plazo (años)",
    "Plazo de pago de primas (años)",
    # Bloque 12
    "Declaración de Salud 'conforme' - Sí",
    "Declaración de Salud 'no conforme' - Sí",
}

# OJO -- hallazgo importante: el título "Beneficios Adicionales al Se...
# de Vida Básico" (usado por extract_bloque_6 para ubicar su sección) NO
# es exclusivo de Options: el PDF de Invest Future usa el MISMO título
# para su propia sección de beneficios (Bloque 6c) -- así que
# extract_bloque_6 también "engancha" y llena captions compartidos
# ("Hospitalización", "Muerte Accidental", "Invalidez Total y
# Permanente", "Exención de Pago de Primas", más el Monto de "Seguro de
# Vida Adicional") bajo el prefijo "VIDA ASEGURADA N -" incluso en
# solicitudes Invest Future (con datos que no coinciden con los campos
# reales del Bloque 6c, que son sin prefijo). Esto es una extracción
# incidental de extract_bloque_6, no algo que este motor deba validar --
# por eso estos 5 conceptos se resuelven por (prefijo, sufijo) exacto acá
# en vez de con los sets genéricos de arriba: la versión CON prefijo
# "VIDA ASEGURADA N -" es siempre del Bloque 6 (solo se chequea si
# Options); la versión SIN prefijo es siempre del Bloque 6c (solo se
# chequea si Invest Future).
_SUFIJOS_BENEFICIO_COMPARTIDO = {
    "Seguro de Vida Adicional - Sí",
    "Seguro de Vida Adicional - No",
    "Seguro de Vida Adicional - Monto",
    "Hospitalización - Sí", "Hospitalización - No", "Hospitalización - Monto",
    "Muerte Accidental - Sí", "Muerte Accidental - No", "Muerte Accidental - Monto",
    "Invalidez Total y Permanente - Sí", "Invalidez Total y Permanente - No",
    "Invalidez Total y Permanente - Monto",
    "Exención de Pago de Primas - Sí", "Exención de Pago de Primas - No",
}


def _saltar_beneficio_compartido(prefix, sufijo, es_options, es_invest_future):
    if prefix.startswith("VIDA ASEGURADA"):
        # extract_bloque_6 no extrae el checkbox Sí/No de "Seguro de Vida
        # Adicional" en NINGUNA familia -- en Options ese beneficio no
        # tiene Sí/No, solo Monto (ver extract_bloque_6); siempre vacío.
        if sufijo in ("Seguro de Vida Adicional - Sí", "Seguro de Vida Adicional - No"):
            return True
        return not es_options
    return not es_invest_future


# Campos sin prefijo que SÍ hay que chequear (Bloques 6c/7/8/9/12/13/14)
# -- el resto de los campos sin prefijo son de Bloque 0 (N° de
# solicitud, fecha, producto) y no se chequean acá.
_CAMPOS_SIN_PREFIJO = _SUFIJOS_SOLO_INVEST_FUTURE | _SUFIJOS_SOLO_OPTIONS | _SUFIJOS_BENEFICIO_COMPARTIDO | {
    "Cuenta Individual - Pesos",
    "Cuenta Individual - Dólares",
    "Primas regulares (A) VRU$S",
    "Prima única (B) VRU$S",
    "Sellado sobre Beneficios (C)",
    "Pago inicial total",
    "Frecuencia de pago - Mensual",
    "Frecuencia de pago - Semestral",
    "Frecuencia de pago - Anual",
    "Origen de los fondos",
    "Titular medio de pago = Solicitante - Sí",
    "Titular medio de pago = Solicitante - No",
    "Medio de pago - Tarjeta de crédito",
    "Tarjeta - Últimos 4 dígitos",
    "Medio de pago - CBU",
    "CBU - Últimos 4 dígitos",
    # Bloque 12 (los que no son "siempre opcional" ni condicionales)
    "Domicilio fiscal del tomador",
    "¿Residencia fiscal fuera de Argentina? - Sí",
    "¿Residencia fiscal fuera de Argentina? - No",
    "¿Contribuyente/residente EE.UU.? - Sí",
    "¿Contribuyente/residente EE.UU.? - No",
    "¿Sujeto Obligado ante la UIF (Art. 20 Ley 25.246)? - Sí",
    "¿Sujeto Obligado ante la UIF? - No",
    "¿Cumple normativa PLA/FT? - Sí",
    "¿Cumple normativa PLA/FT? - No",
    "¿PEP - Persona Expuesta Políticamente? - Sí",
    "¿PEP? - No",
    "PEP - Motivo detallado",
    # Bloque 13
    "Consentimiento de marketing - Marcado",
    # Bloque 14 ("SOLICITANTE CONJUNTO"/"VIDA ASEGURADA 2" se chequean
    # aparte, condicionados a que exista 2da vida -- ver el bloque
    # "if hay_2da_vida" al final de verificar_completitud)
    "FIRMA SOLICITANTE / TOMADOR (aclaración)",
    "FIRMA VIDA ASEGURADA 1 (aclaración)",
    "Productor Asesor - Nombre",
    "Productor Asesor - N° de Productor",
    "Productor Asesor - Matrícula S.S.N.",
}

# Bloques 10/11: por cada Beneficiario Principal/Contingente que tenga
# "Nombre" cargado, qué otros campos de esa misma fila deberían venir
# cargados también (ver docstring del módulo).
_FILAS_BENEFICIARIO_PRINCIPAL = [f"BENEFICIARIO PRINCIPAL {n} - " for n in (1, 2, 3)]
_CAMPOS_FILA_PRINCIPAL = ["Fecha nacimiento", "CUIL/CUIT", "Relación", "%"]
_FILAS_BENEFICIARIO_CONTINGENTE = [f"BENEFICIARIO CONTINGENTE {n} - " for n in (1, 2)]
_CAMPOS_FILA_CONTINGENTE = ["Fecha nacimiento", "CUIL/CUIT", "%"]


def _vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _incompletos_fila(campos, prefix, campos_fila):
    """Si 'Nombre' de esta fila (Beneficiario Principal/Contingente N)
    vino cargado, el resto de los campos de esa misma fila también
    debería estarlo -- si 'Nombre' vino vacío, la fila entera no existe
    (es normal tener menos beneficiarios que el máximo de la tabla) y no
    se chequea nada de ahí."""
    if _vacio(campos.get(prefix + "Nombre")):
        return []
    return [
        f"Falta '{prefix}{campo}' (la fila tiene Nombre cargado)"
        for campo in campos_fila
        if _vacio(campos.get(prefix + campo))
    ]


def verificar_completitud(campos):
    """Devuelve una lista de mensajes "Falta '<campo>'" para los campos
    que vinieron vacíos y deberían estar cargados."""
    incompletos = []

    secciones_ausentes = {
        prefix
        for prefix, centinela in _CENTINELA_SECCION.items()
        if _vacio(campos.get(prefix + centinela))
    }
    hay_2da_vida = "VIDA ASEGURADA 2 - " not in secciones_ausentes
    producto = campos.get("Producto / Formulario")
    es_options = producto == "Zurich Options"
    es_invest_future = producto == "Zurich Invest Future"

    for campo, valor in campos.items():
        if campo in _DERIVADOS_BLOQUE_0:
            continue

        prefix = next((p for p in _PREFIJOS if campo.startswith(p)), "")
        if prefix == "" and campo not in _CAMPOS_SIN_PREFIJO:
            continue  # resto de campos de Bloque 0 (N° de solicitud, fecha, producto, etc.)
        if prefix in secciones_ausentes:
            continue  # toda la sección no aplica a esta solicitud

        sufijo = campo[len(prefix):]
        if sufijo in _SIEMPRE_OPCIONALES:
            continue
        if sufijo in _SUFIJOS_BENEFICIO_COMPARTIDO:
            if _saltar_beneficio_compartido(prefix, sufijo, es_options, es_invest_future):
                continue
        elif sufijo in _SUFIJOS_SOLO_OPTIONS and not es_options:
            continue
        elif sufijo in _SUFIJOS_SOLO_INVEST_FUTURE and not es_invest_future:
            continue

        condicional = next(
            (
                c for c in _CONDICIONALES
                if c[0] == sufijo and (c[2] is None or c[2] == producto)
            ),
            None,
        )
        if condicional is not None:
            _, sufijo_habilitante, _ = condicional
            if campos.get(prefix + sufijo_habilitante) != "Marcado":
                continue  # la pregunta que lo habilita fue "No": vacío es normal

        if _vacio(valor):
            incompletos.append(f"Falta '{campo}'")

    # Asignación de fondos (Bloque 7): si "Estrategia Predeterminada" es
    # "No", tiene que haber AL MENOS un fondo con porcentaje cargado (no
    # los 6, ver _CAMPOS_ASIGNACION_FONDOS).
    if campos.get("Estrategia Predeterminada - No") == "Marcado":
        if all(_vacio(campos.get(c)) for c in _CAMPOS_ASIGNACION_FONDOS):
            incompletos.append(
                "Falta la asignación de fondos (Estrategia Predeterminada = No, "
                "pero ningún fondo tiene porcentaje cargado)"
            )

    # Bloque 11: hay que declarar Opción A o B (en los 5 ejemplos de
    # prueba siempre viene marcada alguna).
    if campos.get("Opción A - declarada") != "Marcado" and campos.get("Opción B - declarada") != "Marcado":
        incompletos.append("Falta declarar la Opción A o B de Beneficiarios Contingentes")

    # Bloques 10/11: consistencia por fila (ver docstring del módulo).
    for prefix in _FILAS_BENEFICIARIO_PRINCIPAL:
        incompletos.extend(_incompletos_fila(campos, prefix, _CAMPOS_FILA_PRINCIPAL))
    for prefix in _FILAS_BENEFICIARIO_CONTINGENTE:
        incompletos.extend(_incompletos_fila(campos, prefix, _CAMPOS_FILA_CONTINGENTE))

    # Bloques 12/14: campos del Solicitante Conjunto / Segunda Vida
    # Asegurada, solo si la solicitud es de 2 vidas (mismo criterio que
    # secciones_ausentes, pero estos 3 campos no usan el prefijo
    # "SOLICITANTE CONJUNTO - "/"VIDA ASEGURADA 2 - " de Bloque 3/4b).
    if hay_2da_vida:
        for campo in (
            "Solicitante Conjunto - Domicilio fiscal",
            "FIRMA SOLICITANTE CONJUNTO (aclaración)",
            "FIRMA VIDA ASEGURADA 2 (aclaración)",
        ):
            if _vacio(campos.get(campo)):
                incompletos.append(f"Falta '{campo}'")

    return incompletos
