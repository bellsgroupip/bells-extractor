"""
Extractor real del AVAL, por coordenadas (pdfplumber), SIN IA.

ESTADO ACTUAL: el AVAL no es un único formato -- son constancias de
ARCA/AFIP/ANSES, pero TAMBIÉN pueden ser facturas de servicios (luz/gas/
teléfono) o resúmenes de tarjeta de crédito (Bells Group aclaró
2026-08-12: cualquiera de estos sirve como "aval de domicilio"). Reconoce
8 plantillas hoy:

1. "Monotributo" (pdfs-prueba/AVAL PAZ, AGUSTIN.pdf) -- Constancia de
   Opción al Régimen Simplificado de ARCA. Trae CUIT, nombre, domicilio
   completo (Calle/Número/Localidad/CP/Provincia), régimen/categoría,
   actividad y vigencia. NO trae DNI ni fecha de nacimiento -- el cruce
   contra la SOLICITUD se hace por CUIT/nombre/domicilio, no por fecha de
   nacimiento (a diferencia del DNI).
2. "CUIL/CUIT" de ANSES (pdfs-prueba/CONSTANCIA_CUIL.pdf) -- título
   literal "Constancia de CUIL/CUIT". Mucho más simple: Titular (nombre),
   Documento (DNI) y CUIL/CUIT. NO trae domicilio ni vigencia -- el propio
   PDF aclara "Esta constancia no tiene vencimiento" -- esos campos quedan
   en None para esta plantilla, no es un bug ni un caso a mejorar.
3 y 4. "Constancia de CUIL" y "Constancia de Inscripción" de ARCA
   (pdfs-prueba/ARCA - CUIL SQUEO NATANAEL ALEXIS.pdf y AFIP - CONSTANCIA -
   DAIVES.pdf / ARCA - AVAL - MIGNONE LUCIANO.pdf, agregados 2026-08-12) --
   exportadas desde el navegador ("Formulario de Impresión de Constancia de
   Inscripción" como primera línea, con fecha/hora -- el título real del
   documento va en la línea siguiente, no en la primera). A diferencia de
   la Constancia de CUIL/CUIT de ANSES, estas SÍ traen domicilio completo
   (etiqueta "DOMICILIO LEGAL/REAL - ARCA" o "DOMICILIO FISCAL - ARCA",
   aparece 2 veces en la de Inscripción -- se toma la primera aparición,
   son el mismo domicilio) y vigencia de la constancia (mismo formato que
   Monotributo). Nombre + CUIT/CUIL vienen juntos en una sola línea
   ("<NOMBRE> CUIT: <valor>" o "<NOMBRE> CUIL: <valor>"). No traen
   Régimen/Categoría/Actividad en el mismo formato que Monotributo (la de
   Inscripción sí lista actividades, pero en un bloque de largo variable
   según cuántos regímenes tenga el contribuyente registrados -- no vale la
   pena parsearlo para lo que se pidió, queda en None). Se procesan las dos
   con la misma función (_extraer_arca) porque comparten estructura
   exacta de Nombre+CUIT / Domicilio / Vigencia.

HALLAZGO REAL (2026-08-11, ejecución 247): un AVAL real (Zurich, cliente
TUERO) resultó ser la plantilla "Constancia de Inscripción" de ARCA (la
misma que se calibró recién, punto 4) todavía no reconocida en ese momento.
La versión vieja de este script asumía SIEMPRE la plantilla Monotributo y
buscaba "CUIT:" en cualquier parte del PDF -- como esa constancia también
tiene esa cadena en otro contexto (una tabla de impuestos), el script
agarró texto de las filas de esa tabla como si fueran Nombre/Calle/
Localidad, generando errores falsos ("Nombre no coincide", "Domicilio no
coincide") en el informe. FIX: la plantilla se detecta por el TÍTULO del
documento (buscado en las primeras líneas, no asumiendo que sea la
primera -- ver arriba) antes de extraer nada -- si no matchea ninguna
plantilla conocida, devuelve todos los campos en None en vez de adivinar.
Avisar apenas aparezca un caso de plantilla no reconocida para calibrar un
patrón nuevo.

5-8. Facturas de servicios (EDESA -electricidad-, GASNOR -gas-, Movistar
   -telefonía-) y resúmenes de tarjeta VISA (agregados 2026-08-12,
   calibrados contra pdfs-prueba/SERVICIO - * .pdf y RESUMEN - * .pdf) --
   a diferencia de las constancias de ARCA/ANSES, estas son facturas con
   layout de varias columnas, sin un campo por línea prolijo: la
   extracción usa regex sobre el texto completo de la página en vez de
   leer "N líneas después de la etiqueta". Traen Nombre + Domicilio (y
   Localidad/CP/Provincia cuando se pudo ubicar, best-effort -- EDESA no
   los trae en un formato reconocible en el único ejemplo disponible).
   NINGUNA trae CUIT/CUIL del titular -- el "CUIT"/"C.U.I.T." que
   aparece en estas facturas es el de la EMPRESA emisora (GASNOR,
   Telefónica, o el banco emisor de la VISA), no el del titular del
   servicio, así que ese campo queda en None a propósito (no es un dato
   faltante, es un dato que no corresponde). Movistar sí trae el
   Documento (DNI) del titular, se guarda en "AVAL - Documento N°" igual
   que en la plantilla CUIL/CUIT de ANSES. Detectadas por palabra clave
   de la empresa/"TITULAR DE CUENTA" en las primeras ~20 líneas (no toda
   la página) -- un resumen de tarjeta puede tener un pago A EDESA/GASNOR
   como una transacción más del listado, y buscar en toda la página
   detectaba erróneamente ESE resumen como si fuera una factura de EDESA
   (hallazgo real 2026-08-12, devolvía todos los campos vacíos porque la
   estructura no coincidía). LÍMITE CONOCIDO: pdfs-prueba/SERVICIO -
   GASNOR.pdf es una foto/escaneo sin capa de texto (0 caracteres
   extraíbles por pdfplumber) -- este módulo no hace OCR (a diferencia de
   extract_dni.py), así que ese caso puntual devuelve todos los campos en
   None. Si llegan muchos AVAL de este tipo como imagen, evaluar agregar
   OCR acá también.

El domicilio (Monotributo y las 2 plantillas de ARCA) viene en una línea
"Calle Número" (ej. "SANTIAGO DEL ESTERO 157"), a veces con un sufijo
"- BARRIO : <nombre> [código]" (ej. "ESTANISLAO DEL CAMPO 1274 - BARRIO :
SAN LORENZO 4401" -- el número de barrio al final NO es la altura, hay que
cortar antes del "- BARRIO"); se separa por el token numérico (o "S/N")
antes de "- BARRIO" si existe, o el último token si no. Si el domicilio es
de barrio sin ese formato (ej. "B° SAN CAYETANO MZA 5 CASA 10") la
separación puede quedar mal dividida -- no se pidió un campo "Barrio"
aparte, así que ese caso queda solo como una Calle mal cortada, no se
pierde el dato.

Uso:
    python3 extract_aval.py "../pdfs-prueba/AVAL PAZ, AGUSTIN.pdf"
    python3 extract_aval.py "../pdfs-prueba/CONSTANCIA_CUIL.pdf"
    python3 extract_aval.py "../pdfs-prueba/ARCA - CUIL SQUEO NATANAEL ALEXIS.pdf"
    python3 extract_aval.py "../pdfs-prueba/AFIP - CONSTANCIA - DAIVES.pdf"
"""

import json
import re
import sys

from pdf_layout import load_lines, find_line


def _clean(s):
    s = (s or "").strip()
    return s if s else None


def _split_calle_numero(domicilio):
    texto = (domicilio or "").strip()
    if not texto:
        return None, None
    # "CALLE NUMERO - BARRIO : NOMBRE [código]" (formato ARCA) -- el
    # número de la altura está ANTES de "- BARRIO", no al final de la
    # línea (ver docstring del módulo).
    m = re.match(r"^(.*\S)\s+(S/N|\d+[A-Za-z°]*)\s*-\s*BARRIO\s*:", texto, re.IGNORECASE)
    if m:
        return _clean(m.group(1)), _clean(m.group(2))
    m = re.match(r"^(.*\S)\s+(S/N|\d+[A-Za-z°]*)$", texto)
    if m:
        return _clean(m.group(1)), _clean(m.group(2))
    return _clean(texto), None


def _campos_vacios():
    return {
        "AVAL - CUIT": None,
        "AVAL - Nombre y Apellido / Razón Social": None,
        "AVAL - Documento N°": None,
        "AVAL - Calle": None,
        "AVAL - Número": None,
        "AVAL - Localidad": None,
        "AVAL - Código Postal": None,
        "AVAL - Provincia": None,
        "AVAL - Régimen": None,
        "AVAL - Categoría": None,
        "AVAL - Actividad (rubro)": None,
        "AVAL - Actividad (código y detalle)": None,
        "AVAL - Fecha de inicio": None,
        "AVAL - Vigencia": None,
    }


def _detectar_plantilla(page0):
    """Detecta la plantilla por el TÍTULO del documento -- no por buscar
    "CUIT" en cualquier parte del PDF, que es lo que causó el hallazgo real
    del 2026-08-11 (ver docstring del módulo). Busca en las primeras
    líneas (no solo la primera): las constancias de ARCA exportadas desde
    el navegador traen una línea de encabezado con fecha/hora ANTES del
    título real del documento."""
    if not page0:
        return None
    encabezado = " | ".join((l["text"] or "") for l in page0[:5]).upper()
    if "CONSTANCIA DE OPCI" in encabezado:
        return "monotributo"
    # OJO: chequear "CUIL/CUIT" (con barra, ANSES) ANTES que "CONSTANCIA
    # DE CUIL" sola (ARCA) -- son plantillas distintas, "CUIL/CUIT" está
    # contenida como substring en cualquier frase que la incluya.
    if "CUIL/CUIT" in encabezado:
        return "cuil_cuit"
    if "CONSTANCIA DE CUIL" in encabezado or "CONSTANCIA DE CUIT" in encabezado:
        return "arca"
    if "CONSTANCIA DE INSCRIPCI" in encabezado:
        return "arca"

    # Facturas de servicios / resúmenes de tarjeta (agregados 2026-08-12,
    # sirven como AVAL de domicilio aunque no sean constancias de ARCA) --
    # estas no tienen un título limpio en la parte de arriba (son facturas
    # con layout de varias columnas), así que se detectan por una palabra
    # clave de la empresa. Se busca solo en las primeras ~20 líneas (zona
    # de encabezado/datos del titular), NO en toda la página -- un
    # resumen de tarjeta puede tener un pago A EDESA/GASNOR/etc. como una
    # transacción más en el listado (hallazgo real: un resumen VISA con
    # "EDESA SA" como transacción se detectaba como factura de EDESA y
    # devolvía todos los campos vacíos). "TITULAR DE CUENTA" se chequea
    # primero porque es la firma más específica de las 4 -- si matchea,
    # no hace falta mirar las demás.
    encabezado_amplio = " | ".join((l["text"] or "") for l in page0[:20]).upper()
    if "TITULAR DE CUENTA" in encabezado_amplio:
        return "visa_resumen"
    if "EDESA" in encabezado_amplio:
        return "edesa"
    if "GASNOR" in encabezado_amplio:
        return "gasnor"
    if "TELEF" in encabezado_amplio:
        return "movistar"
    return None


def _extraer_monotributo(page0, campos):
    # --- CUIT + las 4 líneas siguientes: Nombre, Domicilio, Localidad, CP-Provincia
    # (orden fijo en la plantilla de ARCA)
    idx = find_line(page0, ["CUIT:"])
    if idx is not None:
        m = re.search(r"CUIT:\s*([\d-]+)", page0[idx]["text"])
        if m:
            campos["AVAL - CUIT"] = m.group(1)

        if idx + 1 < len(page0):
            campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(page0[idx + 1]["text"])
        if idx + 2 < len(page0):
            calle, numero = _split_calle_numero(page0[idx + 2]["text"])
            campos["AVAL - Calle"] = calle
            campos["AVAL - Número"] = numero
        if idx + 3 < len(page0):
            campos["AVAL - Localidad"] = _clean(page0[idx + 3]["text"])
        if idx + 4 < len(page0):
            cp_prov = page0[idx + 4]["text"]
            m = re.match(r"(\d+)-(.+)", cp_prov)
            if m:
                campos["AVAL - Código Postal"] = m.group(1)
                campos["AVAL - Provincia"] = _clean(m.group(2))

    # --- Régimen: línea corta tipo "020 - MONOTRIBUTO", antes de "CATEGORÍA"
    idx_cat_label = find_line(page0, ["CATEGOR"])
    if idx_cat_label is not None:
        if idx_cat_label - 1 >= 0:
            campos["AVAL - Régimen"] = _clean(page0[idx_cat_label - 1]["text"])
        if idx_cat_label + 1 < len(page0):
            campos["AVAL - Categoría"] = _clean(page0[idx_cat_label + 1]["text"])

    # --- Actividad: rubro general (línea suelta antes de "FECHA DE INICIO")
    # y actividad puntual (línea "ACTIVIDAD: <código> - <detalle>")
    idx_fecha = find_line(page0, ["FECHA DE INICIO:"])
    if idx_fecha is not None and idx_fecha - 1 >= 0:
        campos["AVAL - Actividad (rubro)"] = _clean(page0[idx_fecha - 1]["text"])
    if idx_fecha is not None:
        m = re.search(r"FECHA DE INICIO:\s*([\d-]+)", page0[idx_fecha]["text"])
        if m:
            campos["AVAL - Fecha de inicio"] = m.group(1)

    idx_act = find_line(page0, ["ACTIVIDAD:"])
    if idx_act is not None:
        m = re.search(r"ACTIVIDAD:\s*(.+)", page0[idx_act]["text"])
        if m:
            campos["AVAL - Actividad (código y detalle)"] = _clean(m.group(1))

    # --- Vigencia: "Vigencia de la presente constancia: <desde> a <hasta> Hora ..."
    idx_vig = find_line(page0, ["Vigencia", "de", "la", "presente", "constancia:"])
    if idx_vig is not None:
        m = re.search(
            r"constancia:\s*([\d-]+)\s+a\s+([\d-]+)", page0[idx_vig]["text"]
        )
        if m:
            campos["AVAL - Vigencia"] = f"{m.group(1)} a {m.group(2)}"


def _extraer_arca(page0, campos):
    """Constancia de CUIL o de Inscripción de ARCA (ver docstring del
    módulo) -- comparten estructura: Nombre + CUIT/CUIL en una sola línea,
    domicilio de 3 líneas después de la primera etiqueta "DOMICILIO..."
    (aparece 2 veces en la de Inscripción, se toma la primera), y vigencia
    de la constancia en el mismo formato que Monotributo."""
    idx_nombre = None
    for i, linea in enumerate(page0):
        m = re.search(r"^(.+?)\s+CUI[LT]:\s*([\d.-]+)", linea["text"])
        if m:
            idx_nombre = i
            campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(m.group(1))
            campos["AVAL - CUIT"] = _clean(m.group(2))
            break

    idx_dom = find_line(page0, ["DOMICILIO"], start=(idx_nombre or 0) + 1)
    if idx_dom is not None:
        if idx_dom + 1 < len(page0):
            calle, numero = _split_calle_numero(page0[idx_dom + 1]["text"])
            campos["AVAL - Calle"] = calle
            campos["AVAL - Número"] = numero
        if idx_dom + 2 < len(page0):
            campos["AVAL - Localidad"] = _clean(page0[idx_dom + 2]["text"])
        if idx_dom + 3 < len(page0):
            cp_prov = page0[idx_dom + 3]["text"]
            m = re.match(r"(\d+)-(.+)", cp_prov)
            if m:
                campos["AVAL - Código Postal"] = m.group(1)
                campos["AVAL - Provincia"] = _clean(m.group(2))

    idx_vig = find_line(page0, ["Vigencia", "de", "la", "presente", "constancia:"])
    if idx_vig is not None:
        m = re.search(
            r"constancia:\s*([\d-]+)\s+a\s+([\d-]+)", page0[idx_vig]["text"]
        )
        if m:
            campos["AVAL - Vigencia"] = f"{m.group(1)} a {m.group(2)}"


def _extraer_gasnor(page0, campos):
    """Factura de servicio de gas (GASNOR) -- layout de varias columnas,
    no de un campo por línea como las constancias de ARCA. Se busca cada
    etiqueta con regex sobre el texto completo en vez de por posición."""
    texto = "\n".join(l["text"] for l in page0)

    m = re.search(r"Sr\.?/a:\s*(.+)", texto)
    if m:
        campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(m.group(1))

    m = re.search(r"Domicilio Servicio:\s*(.+?)(?:\s+Subtotal|\n|$)", texto)
    if m:
        calle, numero = _split_calle_numero(m.group(1))
        campos["AVAL - Calle"] = calle
        campos["AVAL - Número"] = numero

    m = re.search(r"Localidad:\s*(\S+)", texto)
    if m:
        campos["AVAL - Localidad"] = _clean(m.group(1))

    m = re.search(r"Provincia:\s*(\S+)\s+CP:\s*(\d+)", texto)
    if m:
        campos["AVAL - Provincia"] = _clean(m.group(1))
        campos["AVAL - Código Postal"] = m.group(2)


def _extraer_edesa(page0, campos):
    """Factura de servicio eléctrico (EDESA) -- mismo criterio que GASNOR
    (regex sobre texto completo, no por posición fija). El nombre no tiene
    etiqueta propia -- es la primera línea con forma "APELLIDO, NOMBRE"
    seguida de números de cuenta."""
    texto = "\n".join(l["text"] for l in page0)

    m = re.search(
        r"^([A-ZÁÉÍÓÚÑ]+(?:\s[A-ZÁÉÍÓÚÑ]+)*,\s*[A-ZÁÉÍÓÚÑ]+(?:\s[A-ZÁÉÍÓÚÑ]+)*)\s+\d{5,}",
        texto,
        re.MULTILINE,
    )
    if m:
        campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(m.group(1))

    m = re.search(r"Domicilio\s*:\s*(.+?)(?:\s+Subtotal|\n|$)", texto)
    if m:
        valor = m.group(1).strip()
        # el domicilio suele seguir en la línea de abajo (ej. "ETAPA II")
        # antes de "Subtotal ..." -- se pega si no es otro campo con ":"
        fin = m.end()
        resto = texto[fin:].split("\n", 2)
        if resto and resto[0].strip() and ":" not in resto[0]:
            # cortar también acá antes de "Subtotal" -- puede venir
            # pegado en la MISMA línea que el resto del domicilio
            # (ej. "ETAPA II Subtotal EDESA SA 6.892,73").
            siguiente = re.split(r"\s+Subtotal\b", resto[0].strip(), maxsplit=1)[0]
            if siguiente:
                valor = f"{valor} {siguiente}"
        calle, numero = _split_calle_numero(valor)
        campos["AVAL - Calle"] = calle
        campos["AVAL - Número"] = numero


def _extraer_movistar(page0, campos):
    """Factura de telefonía móvil (Movistar) -- mismo criterio que GASNOR/
    EDESA. Trae el Documento (DNI) del titular, NO CUIT -- el "C.U.I.T"
    que aparece en el encabezado es el de Telefónica Móviles Argentina
    S.A. (la empresa), no del titular de la línea."""
    texto = "\n".join(l["text"] for l in page0)

    idx_cuit_empresa = find_line(page0, ["C.U.I.T"])
    if idx_cuit_empresa is not None and idx_cuit_empresa + 1 < len(page0):
        m = re.match(r"^(.+?)\s+Ingresos Brutos", page0[idx_cuit_empresa + 1]["text"])
        if m:
            campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(m.group(1))

    idx_domicilio = (idx_cuit_empresa or 0) + 3
    if idx_domicilio < len(page0):
        valor = re.sub(r"\s+(ORIGINAL|DUPLICADO)\s*$", "", page0[idx_domicilio]["text"], flags=re.IGNORECASE)
        calle, numero = _split_calle_numero(valor)
        campos["AVAL - Calle"] = calle
        campos["AVAL - Número"] = numero

    m = re.search(r"\(([A-Z]\d{4}[A-Z]{3})\)\s+([A-ZÁÉÍÓÚÑ]+)\s+Vencimiento", texto)
    if m:
        campos["AVAL - Código Postal"] = m.group(1)
        campos["AVAL - Localidad"] = m.group(2)

    m = re.search(r"Documento Nacional Identidad:\s*(\d+)", texto)
    if m:
        campos["AVAL - Documento N°"] = m.group(1)


def _extraer_visa_resumen(page0, campos):
    """Resumen de cuenta de tarjeta VISA -- mismo criterio de regex sobre
    texto completo. El "CUIT" que trae el encabezado es del banco/emisor
    de la tarjeta, NO del titular -- un resumen de tarjeta no muestra el
    CUIT/CUIL personal del titular, así que ese campo queda en None acá a
    propósito (no hay nada que extraer, no es un bug)."""
    texto = "\n".join(l["text"] for l in page0)

    m = re.search(r"^([A-ZÁÉÍÓÚÑ\s]+?)\s+CIERRE ACTUAL:", texto, re.MULTILINE)
    if not m:
        m = re.search(r"TITULAR DE CUENTA:\s*(.+)", texto)
    if m:
        campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(m.group(1))

    m = re.search(r"^(.+?)\s+VENCIMIENTO\s+SALDO", texto, re.MULTILINE)
    if m:
        calle, numero = _split_calle_numero(m.group(1))
        campos["AVAL - Calle"] = calle
        campos["AVAL - Número"] = numero

    m = re.search(r"^(\d{4})\s+([A-ZÁÉÍÓÚÑ]+)\s", texto, re.MULTILINE)
    if m:
        campos["AVAL - Código Postal"] = m.group(1)
        campos["AVAL - Localidad"] = m.group(2)

    m = re.search(r"PROV\s+([A-ZÁÉÍÓÚÑ]+)\s+SUC", texto)
    if m:
        campos["AVAL - Provincia"] = m.group(1)


def _extraer_cuil_cuit(page0, campos):
    # --- Titular / Documento / CUIL-CUIT: 3 bloques de "etiqueta en una
    # línea, valor en la siguiente", en ese orden fijo (constancia ANSES).
    idx_titular = find_line(page0, ["Titular"])
    if idx_titular is not None and idx_titular + 1 < len(page0):
        campos["AVAL - Nombre y Apellido / Razón Social"] = _clean(page0[idx_titular + 1]["text"])

    idx_doc = find_line(page0, ["Documento"], start=(idx_titular or 0) + 1)
    if idx_doc is not None and idx_doc + 1 < len(page0):
        m = re.search(r"(\d[\d.]*\d|\d)", page0[idx_doc + 1]["text"])
        if m:
            campos["AVAL - Documento N°"] = m.group(1).replace(".", "")

    idx_cuil = find_line(page0, ["CUIL/CUIT"], start=(idx_doc or 0) + 1)
    if idx_cuil is not None and idx_cuil + 1 < len(page0):
        campos["AVAL - CUIT"] = _clean(page0[idx_cuil + 1]["text"])


def extract_aval(pdf_path):
    pages = load_lines(pdf_path)
    page0 = pages[0]
    campos = _campos_vacios()

    plantilla = _detectar_plantilla(page0)
    if plantilla == "monotributo":
        _extraer_monotributo(page0, campos)
    elif plantilla == "cuil_cuit":
        _extraer_cuil_cuit(page0, campos)
    elif plantilla == "arca":
        _extraer_arca(page0, campos)
    elif plantilla == "gasnor":
        _extraer_gasnor(page0, campos)
    elif plantilla == "edesa":
        _extraer_edesa(page0, campos)
    elif plantilla == "movistar":
        _extraer_movistar(page0, campos)
    elif plantilla == "visa_resumen":
        _extraer_visa_resumen(page0, campos)
    # Si no matchea ninguna plantilla conocida, se devuelven todos los
    # campos en None -- mejor eso que extraer texto de las líneas
    # equivocadas (ver hallazgo real en el docstring del módulo).

    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_aval.py <ruta_al_pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    campos = extract_aval(pdf_path)
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
