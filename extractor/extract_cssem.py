"""
Extractor real del "Cuestionario de Salud Sin Examen Médico" (CSSEM) de
Zurich, por coordenadas (pdfplumber), SIN IA.

ESTADO ACTUAL / ALCANCE:
No se implementa el formulario completo (12 preguntas de "Datos médicos") --
Bells Group solo pidió una regla puntual: si la Pregunta 7 ("¿Ha consultado
a un médico...? ¿...ha sido sometido...a algún tipo de examen o
investigación médica...?") está marcada "Sí", extraer la fecha declarada
para poder compararla, en el workflow, contra la "Fecha de solicitud" de la
SOLICITUD (ver check en el nodo "Consolidar y Chequear": si la consulta/
examen fue hecho dentro de los 3 meses de la fecha de la Solicitud, avisa
que Zurich va a pedir los análisis; si fue hecho hace más de 3 meses, puede
no pedirlos).

La fecha de la Pregunta 7 viene en formato "MM/AAAA" (sin día) en el único
ejemplo disponible (pdfs-prueba/CSSEM -DS-.pdf, Fecha: 05/2025) -- se
parsea tolerando también "DD/MM/AAAA" por si en otro caso viene con día.

Uso:
    python3 extract_cssem.py "../pdfs-prueba/CSSEM -DS-.pdf"
"""

import json
import re
import sys

from pdf_layout import load_lines, find_line, checkbox_marked, word_x0


def _clean(s):
    s = (s or "").strip()
    return s if s else None


def _flatten(pages):
    return [line for page in pages for line in page]


def _value_after_label(line, etiqueta):
    # Búsqueda simple por substring del texto crudo, ya que estas etiquetas
    # ("Razón:", "Fecha:", "Resultado:") no comparten línea con otro dato.
    idx = line["text"].find(etiqueta)
    if idx == -1:
        return None
    return line["text"][idx + len(etiqueta):].strip()


def extract_cssem(pdf_path):
    pages = load_lines(pdf_path)
    all_lines = _flatten(pages)

    campos = {
        "CSSEM - Nombre y Apellido": None,
        "CSSEM - Documento N°": None,
        "Pregunta 7 - Consulta/examen médico reciente - Sí": "No marcado",
        "Pregunta 7 - Consulta/examen médico reciente - No": "No marcado",
        "Pregunta 7 - Razón": None,
        "Pregunta 7 - Fecha": None,
        "Pregunta 7 - Resultado": None,
    }

    # --- Nombre/Apellido + Documento (Bloque "2. Datos del Asegurado") ---
    idx = find_line(all_lines, ["Nombre/s", "Apellido/s"])
    if idx is not None:
        line = all_lines[idx]
        x_nombre = word_x0(line, "Apellido/s")
        x_ini = None
        for w in line["words"]:
            if w["text"] == "Nombre/s":
                x_ini = w["x1"]
                break
        nombre = None
        apellido = None
        if x_ini is not None and x_nombre is not None:
            nombre = " ".join(
                w["text"] for w in line["words"] if x_ini <= w["x0"] < x_nombre
            ).strip()
            x_fin_apellido = None
            for w in line["words"]:
                if w["text"] == "Apellido/s":
                    x_fin_apellido = w["x1"]
                    break
            apellido = " ".join(
                w["text"] for w in line["words"] if x_fin_apellido and w["x0"] >= x_fin_apellido
            ).strip()
        if nombre or apellido:
            campos["CSSEM - Nombre y Apellido"] = _clean(f"{nombre or ''} {apellido or ''}".strip())

    idx = find_line(all_lines, ["Documento", "indique tipo", "N"])
    if idx is not None:
        m = re.search(r"N[º°]\s*([\dA-Za-z.]+)\s*$", all_lines[idx]["text"])
        if m:
            campos["CSSEM - Documento N°"] = _clean(m.group(1))

    # --- Pregunta 7 ---
    idx = find_line(all_lines, "Ha consultado a un médico")
    if idx is not None:
        line = all_lines[idx]
        x_si = word_x0(line, "Sí")
        x_no = word_x0(line, "No")
        campos["Pregunta 7 - Consulta/examen médico reciente - Sí"] = (
            checkbox_marked(line, x_si) if x_si is not None else "No marcado"
        )
        campos["Pregunta 7 - Consulta/examen médico reciente - No"] = (
            checkbox_marked(line, x_no) if x_no is not None else "No marcado"
        )

        # El detalle (Razón/Fecha/Resultado) cae en las líneas siguientes,
        # hasta la Pregunta 8 -- solo tiene sentido leerlo si se marcó "Sí".
        if campos["Pregunta 7 - Consulta/examen médico reciente - Sí"] == "Marcado":
            idx_fin = find_line(all_lines, "¿Ha tenido o tiene alguna otra enfermedad", start=idx + 1)
            limite = idx_fin if idx_fin is not None else idx + 6
            for j in range(idx + 1, min(limite, len(all_lines))):
                texto = all_lines[j]["text"]
                if texto.startswith("Razón:"):
                    campos["Pregunta 7 - Razón"] = _clean(_value_after_label(all_lines[j], "Razón:"))
                elif texto.startswith("Fecha:"):
                    campos["Pregunta 7 - Fecha"] = _clean(_value_after_label(all_lines[j], "Fecha:"))
                elif texto.startswith("Resultado:"):
                    campos["Pregunta 7 - Resultado"] = _clean(_value_after_label(all_lines[j], "Resultado:"))

    return campos


if __name__ == "__main__":
    resultado = extract_cssem(sys.argv[1])
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
