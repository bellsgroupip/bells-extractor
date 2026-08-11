"""
Extractor real del AVAL, por coordenadas (pdfplumber), SIN IA.

ESTADO ACTUAL / SUPUESTO IMPORTANTE:
El único ejemplo de AVAL disponible hoy (pdfs-prueba/AVAL PAZ, AGUSTIN.pdf)
es una Constancia de Opción al Régimen Simplificado (Monotributo) que emite
ARCA/AFIP -- no una carta de garantía personal. Este script asume esa
plantilla (es un PDF generado por el sitio de ARCA, con texto seleccionable
y estructura fija). Si en la práctica llega un AVAL con otro formato (otra
constancia, una nota escaneada, etc.), este extractor no lo va a reconocer
y hace falta un patrón nuevo -- avisar apenas aparezca un caso así.

Esta plantilla no trae DNI ni fecha de nacimiento, solo CUIT. El chequeo
cruzado contra la SOLICITUD debería hacerse por CUIT/nombre, no por fecha
de nacimiento (a diferencia del DNI).

El domicilio viene en una sola línea "Calle Número" (ej. "SANTIAGO DEL
ESTERO 157"); se separa por el último token si es numérico o "S/N", igual
que la SOLICITUD separa Calle/Número. Si el domicilio es de barrio (sin
calle+altura, ej. "B° SAN CAYETANO MZA 5 CASA 10") la separación puede
quedar mal dividida -- no se pidió un campo "Barrio" aparte, así que ese
caso queda solo como una Calle mal cortada, no se pierde el dato.

Uso:
    python3 extract_aval.py "../pdfs-prueba/AVAL PAZ, AGUSTIN.pdf"
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


def extract_aval(pdf_path):
    pages = load_lines(pdf_path)
    page0 = pages[0]

    campos = {
        "AVAL - CUIT": None,
        "AVAL - Nombre y Apellido / Razón Social": None,
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
