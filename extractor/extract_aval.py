"""
Extractor real del AVAL, por coordenadas (pdfplumber), SIN IA.

ESTADO ACTUAL: el AVAL no es un único formato -- son constancias de
ARCA/AFIP/ANSES (no una carta de garantía personal), y hay más de una
plantilla válida. Reconoce 2 hoy:

1. "Monotributo" (pdfs-prueba/AVAL PAZ, AGUSTIN.pdf) -- Constancia de
   Opción al Régimen Simplificado de ARCA. Trae CUIT, nombre, domicilio
   completo (Calle/Número/Localidad/CP/Provincia), régimen/categoría,
   actividad y vigencia. NO trae DNI ni fecha de nacimiento -- el cruce
   contra la SOLICITUD se hace por CUIT/nombre/domicilio, no por fecha de
   nacimiento (a diferencia del DNI).
2. "CUIL/CUIT" (pdfs-prueba/CONSTANCIA_CUIL.pdf) -- Constancia de CUIL/CUIT
   de ANSES. Mucho más simple: Titular (nombre), Documento (DNI) y
   CUIL/CUIT. NO trae domicilio -- los campos de domicilio/régimen quedan
   en None para esta plantilla.

HALLAZGO REAL (2026-08-11, ejecución 247): un AVAL real (Zurich, cliente
TUERO) resultó ser una TERCERA plantilla de ARCA no reconocida (parece una
Constancia de Inscripción general, mencionaba "IMPUESTOS/REGÍMENES
NACIONALES REGISTRADOS", "GANANCIAS PERSONAS FÍSICAS", "IVA"). La versión
vieja de este script asumía SIEMPRE la plantilla Monotributo y buscaba
"CUIT:" en cualquier parte del PDF -- como esa constancia también tiene esa
cadena en otro contexto (una tabla de impuestos), el script agarró texto de
las filas de esa tabla como si fueran Nombre/Calle/Localidad, generando
errores falsos ("Nombre no coincide", "Domicilio no coincide") en el
informe. FIX: ahora la plantilla se detecta por la PRIMERA LÍNEA del PDF
(título del documento) antes de extraer nada -- si no matchea ninguna
plantilla conocida, devuelve todos los campos en None en vez de adivinar.
Avisar apenas aparezca un caso de plantilla no reconocida para calibrar un
patrón nuevo (como se hizo acá con la de CUIL/CUIT).

El domicilio (solo plantilla Monotributo) viene en una sola línea "Calle
Número" (ej. "SANTIAGO DEL ESTERO 157"); se separa por el último token si
es numérico o "S/N", igual que la SOLICITUD separa Calle/Número. Si el
domicilio es de barrio (sin calle+altura, ej. "B° SAN CAYETANO MZA 5 CASA
10") la separación puede quedar mal dividida -- no se pidió un campo
"Barrio" aparte, así que ese caso queda solo como una Calle mal cortada, no
se pierde el dato.

Uso:
    python3 extract_aval.py "../pdfs-prueba/AVAL PAZ, AGUSTIN.pdf"
    python3 extract_aval.py "../pdfs-prueba/CONSTANCIA_CUIL.pdf"
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
    """Detecta la plantilla por el TÍTULO del documento (primera línea) --
    no por buscar "CUIT" en cualquier parte del PDF, que es lo que causó el
    hallazgo real del 2026-08-11 (ver docstring del módulo)."""
    if not page0:
        return None
    primera = (page0[0]["text"] or "").upper()
    if "CONSTANCIA DE OPCI" in primera:
        return "monotributo"
    if "CONSTANCIA DE CUIL" in primera or "CONSTANCIA DE CUIT" in primera:
        return "cuil_cuit"
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
