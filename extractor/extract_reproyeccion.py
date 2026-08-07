"""
Extractor real de la REPROYECCIÓN, por coordenadas (pdfplumber), SIN IA.

ESTADO ACTUAL / SUPUESTO IMPORTANTE:
El único ejemplo disponible hoy (pdfs-prueba/PROYECCION.pdf) es una
"Proyección" de Zurich Invest Future generada por un sistema externo (DCP
Consulting), con texto seleccionable y estructura de líneas simple (no es
un formulario con checkboxes por coordenada, es más bien un reporte). Si
en la práctica llega una Reproyección con otro formato (Options, u otro
generador), este extractor no lo va a reconocer y hace falta revisar los
patrones -- avisar apenas aparezca un caso así.

Pedido de Bells Group (2026-08-07): extraer el lugar de residencia
declarado (para cruzarlo más adelante contra el domicilio del AVAL) y el
número de proyección (para cruzarlo contra el "N° de Solicitud / Póliza"
de la SOLICITUD -- deben coincidir, es el mismo número de trámite).

El número de proyección aparece en el pie de cada página con el patrón
"<número> - <página> de <total>" (ej. "1492236 - 1 de 5"); se lee de la
primera página, no hace falta repetirlo por página.

Uso:
    python3 extract_reproyeccion.py "../pdfs-prueba/PROYECCION.pdf"
"""

import json
import re
import sys

from pdf_layout import find_line, load_lines


def _clean(s):
    s = (s or "").strip()
    return s if s else None


def extract_reproyeccion(pdf_path):
    pages = load_lines(pdf_path)
    page0 = pages[0]

    campos = {
        "REPROYECCIÓN - N° de Proyección": None,
        "REPROYECCIÓN - Tomador": None,
        "REPROYECCIÓN - Lugar de residencia": None,
    }

    idx = find_line(page0, ["Tomador:"])
    if idx is not None:
        m = re.search(r"Tomador:\s*(.+)$", page0[idx]["text"])
        if m:
            campos["REPROYECCIÓN - Tomador"] = _clean(m.group(1))

    idx = find_line(page0, ["Solicitante residente en:"])
    if idx is not None:
        m = re.search(r"Solicitante residente en:\s*(.+)$", page0[idx]["text"])
        if m:
            campos["REPROYECCIÓN - Lugar de residencia"] = _clean(m.group(1))

    for line in page0:
        m = re.match(r"^(\d+)\s*-\s*\d+\s*de\s*\d+$", line["text"].strip())
        if m:
            campos["REPROYECCIÓN - N° de Proyección"] = m.group(1)
            break

    return campos


if __name__ == "__main__":
    resultado = extract_reproyeccion(sys.argv[1])
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
