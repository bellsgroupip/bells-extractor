"""
Motor de completitud (MVP) para los campos que hoy extrae
extract_solicitud.py (Bloques 0, 2, 3, 4, 4b, 5, 6, 7, 8 y 9). Marca qué
campos vinieron vacíos y deberían estar cargados.

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
Esa familia SÍ cambia qué se chequea a partir del Bloque 6: los campos de
Beneficios Options (Seguro de Vida Adicional, Enfermedad Grave, etc.)
solo se piden si "Producto / Formulario" es "Zurich Options" -- Invest
Future tiene su propia sección de beneficios ("6c", todavía no
implementada), y sin este filtro toda solicitud Invest Future aparecería
con esos campos marcados "incompletos" por error. Al revés en el Bloque 7:
"Pago en adición a Cuenta Individual", "Estrategia Predeterminada" y los
6 "Asignación Zurich X %" son exclusivos de Invest Future (confirmado
contra Base_Combinada) y solo se piden si el producto es Invest Future;
"Cuenta Individual - Pesos/Dólares" en cambio es común a ambas familias.
Los 6 campos de asignación de fondos, además, solo se piden si
"Estrategia Predeterminada" quedó en "No" (si es "Sí" no hay tabla manual
que completar). Mismo patrón en el Bloque 8: "Póliza Vanishing" y
"Actualización de Primas y Beneficios" son de Options; "Incremento anual
automático" (con su nivel y plazo) y "Plazo de pago de primas (años)" son
de Invest Future.

"Vacío legítimo" (de la hoja Leyenda de la Base_Combinada + lo observado
en los 5 ejemplos reales): Piso, Departamento, Tel. celular y todo el
domicilio de correspondencia son opcionales siempre. El detalle de
actividad peligrosa, el detalle de tabaco y los datos de viaje al
exterior son opcionales SALVO que la pregunta Sí/No correspondiente haya
sido contestada "Sí" -- ahí si vienen vacíos sí es información
incompleta de verdad.

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
    # "Seguro de Vida Adicional" no tiene checkbox Sí/No en el PDF -- el
    # extractor deja estos dos siempre en None (ver extract_bloque_6),
    # así que no tiene sentido pedirlos.
    "Seguro de Vida Adicional - Sí",
    "Seguro de Vida Adicional - No",
    # Se chequean como grupo al final de verificar_completitud, no campo
    # por campo (ver _CAMPOS_ASIGNACION_FONDOS).
    "Asignación Zurich Money %",
    "Asignación Zurich Income / Income II %",
    "Asignación Zurich Performance %",
    "Asignación Zurich Commodities %",
    "Asignación Zurich Performance International II % (dólar)",
    "Asignación Zurich Performance Tech % (dólar)",
}

# (sufijo del campo dependiente, sufijo del checkbox "Sí" que lo habilita)
_CONDICIONALES = [
    ("Actividad peligrosa - Detalle", "Actividad peligrosa - Sí"),
    ("Actividad peligrosa - Frecuencia", "Actividad peligrosa - Sí"),
    ("Tabaco - Producto y cantidad diaria", "¿Fumador últimos 12 meses? - Sí"),
    ("Exterior - País", "¿Visitar/residir/trabajar en otro país? - Sí"),
    ("Exterior - Razón", "¿Visitar/residir/trabajar en otro país? - Sí"),
    ("Exterior - Visitas al año", "¿Visitar/residir/trabajar en otro país? - Sí"),
    ("Exterior - Plazo por visita", "¿Visitar/residir/trabajar en otro país? - Sí"),
    ("Detalle otras solicitudes", "Otra solicitud últimos 6 meses - Sí"),
    ("Detalle rechazo/reclamo", "Rechazo/condición especial - Sí"),
    ("Enfermedad Grave - Monto", "Enfermedad Grave - Sí"),
    ("Renta Familiar - Monto anual", "Renta Familiar - Sí"),
    ("Renta Familiar - Años", "Renta Familiar - Sí"),
    ("Muerte Accidental - Monto", "Muerte Accidental - Sí"),
    ("Hospitalización - Monto", "Hospitalización - Sí"),
    ("Invalidez Total y Permanente - Monto", "Invalidez Total y Permanente - Sí"),
    ("Pérdida de Miembros - Monto", "Pérdida de Miembros - Sí"),
    ("Póliza Vanishing - Años", "¿Póliza Vanishing? - Sí"),
    ("Incremento anual - Plazo (años)", "Incremento anual automático - Sí"),
    ("Plazo de pago de primas (años)", "Incremento anual automático - Sí"),
    ("Tarjeta - Últimos 4 dígitos", "Medio de pago - Tarjeta de crédito"),
    ("CBU - Últimos 4 dígitos", "Medio de pago - CBU"),
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

# Bloque 6 (Beneficios Options) solo existe en pólizas Options -- Invest
# Future tiene su propia sección de beneficios ("6c", no implementada
# todavía). Sin este filtro, toda solicitud Invest Future aparecería con
# estos ~16 campos "incompletos" por error (nunca van a tener dato).
_SUFIJOS_SOLO_OPTIONS = {
    suf
    for base in (
        "Seguro de Vida Adicional", "Enfermedad Grave", "Renta Familiar",
        "Muerte Accidental", "Hospitalización", "Invalidez Total y Permanente",
        "Pérdida de Miembros", "Exención de Pago de Primas",
    )
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

# Campos "sueltos" de los Bloques 7/8 (sin prefijo Solicitante/Vida
# Asegurada). "Cuenta Individual - Pesos/Dólares" y "Frecuencia de pago -
# ..." son de ambas familias; el resto es exclusivo de Invest Future
# (confirmado contra Base_Combinada: vienen "N/A" en las solicitudes
# Options de prueba).
_SUFIJOS_SOLO_INVEST_FUTURE = {
    "Pago en adición a Cuenta Individual - Sí",
    "Pago en adición a Cuenta Individual - No",
    "Estrategia Predeterminada - Sí",
    "Estrategia Predeterminada - No",
    "Asignación Zurich Money %",
    "Asignación Zurich Income / Income II %",
    "Asignación Zurich Performance %",
    "Asignación Zurich Commodities %",
    "Asignación Zurich Performance International II % (dólar)",
    "Asignación Zurich Performance Tech % (dólar)",
    "Incremento anual automático - Sí",
    "Incremento anual automático - No",
    "Incremento anual - 5%",
    "Incremento anual - 10%",
    "Incremento anual - Plazo (años)",
    "Plazo de pago de primas (años)",
}

# Campos sin prefijo que SÍ hay que chequear (Bloques 7/8/9) -- el resto
# de los campos sin prefijo son de Bloque 0 (N° de solicitud, fecha,
# producto) y no se chequean acá.
_CAMPOS_SIN_PREFIJO = _SUFIJOS_SOLO_INVEST_FUTURE | _SUFIJOS_SOLO_OPTIONS | {
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
}


def _vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def verificar_completitud(campos):
    """Devuelve una lista de mensajes "Falta '<campo>'" para los campos de
    los Bloques 0/2/3/4/4b que vinieron vacíos y deberían estar cargados."""
    incompletos = []

    secciones_ausentes = {
        prefix
        for prefix, centinela in _CENTINELA_SECCION.items()
        if _vacio(campos.get(prefix + centinela))
    }
    es_options = campos.get("Producto / Formulario") == "Zurich Options"
    es_invest_future = campos.get("Producto / Formulario") == "Zurich Invest Future"

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
        if sufijo in _SUFIJOS_SOLO_OPTIONS and not es_options:
            continue
        if sufijo in _SUFIJOS_SOLO_INVEST_FUTURE and not es_invest_future:
            continue

        condicional = next((c for c in _CONDICIONALES if c[0] == sufijo), None)
        if condicional is not None:
            _, sufijo_habilitante = condicional
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

    return incompletos
