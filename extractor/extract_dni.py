"""
Extractor real del DNI (frente), con OCR (Tesseract vía pytesseract), SIN IA
de interpretación -- el OCR solo convierte píxeles en texto, después se lee
por posición igual que en extract_solicitud.py / extract_aval.py.

SUPUESTO IMPORTANTE (ver también extract_aval.py):
El único ejemplo disponible (pdfs-prueba/DNI PAZ, AGUSTIN.pdf) es el DNI
tarjeta argentino "nuevo formato" (el celeste con foto a la izquierda y
campos bilingües Apellido/Surname, Nombre/Name, etc., más una página con el
dorso/MRZ). Los nombres de campo y el recorte fijo para el N° de Documento
están calibrados sobre ESTE ejemplo. Si llega un DNI fotografiado torcido,
recortado distinto, o el modelo viejo "libreta celeste", este extractor
probablemente no lo lea bien -- avisar apenas aparezca un caso así para
ajustar el recorte o sumar un segundo patrón.

Por qué el N° de Documento se recorta aparte (no sale con el OCR de toda
la página): esa zona de la tarjeta tiene una textura de seguridad (fondo
ondulado) que confunde al OCR cuando se le da toda la imagen junta -- queda
directamente ausente del texto general. Se lo recorta como una región fija
(fracción del ancho/alto de la imagen) y se lee con Tesseract restringido
a dígitos.

Uso:
    python3 extract_dni.py "../pdfs-prueba/DNI PAZ, AGUSTIN.pdf"
"""

import json
import os
import re
import sys

import pdfplumber
import pytesseract
from PIL import ImageOps

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESSDATA_DIR = os.path.join(_HERE, "tessdata")
os.environ.setdefault("TESSDATA_PREFIX", _TESSDATA_DIR)

_TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(_TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

RESOLUTION = 300
LINE_TOLERANCE = 25  # px -- más ancho que en pdf_layout.py porque las cajas de OCR son más ruidosas que el texto nativo del PDF


def _group_lines(ocr_data):
    words = []
    for i in range(len(ocr_data["text"])):
        t = ocr_data["text"][i].strip()
        if not t:
            continue
        words.append({"text": t, "x0": ocr_data["left"][i], "top": ocr_data["top"][i]})
    words.sort(key=lambda w: w["top"])

    lines = []
    for w in words:
        placed = False
        for line in lines:
            if abs(line["top"] - w["top"]) <= LINE_TOLERANCE:
                line["words"].append(w)
                n = len(line["words"])
                line["top"] = (line["top"] * (n - 1) + w["top"]) / n
                placed = True
                break
        if not placed:
            lines.append({"top": w["top"], "words": [w]})

    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
        line["text"] = " ".join(w["text"] for w in line["words"])
    lines.sort(key=lambda l: l["top"])
    return lines


def _find_caption(lines, *fragments, start=0):
    for i in range(start, len(lines)):
        text = lines[i]["text"]
        if all(f in text for f in fragments):
            return i
    return None


def _value_line(lines, idx, max_dy=200):
    """Devuelve la primera línea con contenido real después de la etiqueta
    (saltea líneas de puro ruido de OCR, ej. un '!' o una 'E' sueltos que a
    veces quedan solos entre la etiqueta y el valor)."""
    if idx is None:
        return None
    base_top = lines[idx]["top"]
    for j in range(idx + 1, len(lines)):
        if lines[j]["top"] - base_top > max_dy:
            break
        cand = lines[j]["text"].strip()
        if len(re.sub(r"[^A-Za-z0-9]", "", cand)) >= 2:
            return cand
    return None


def _solo_letras(text):
    """De una línea de OCR con ruido (signos sueltos, artefactos), se queda
    solo con las secuencias de 2+ letras mayúsculas -- así se descarta basura
    tipo '!' o '4' que a veces cuelga cerca del texto real."""
    return " ".join(re.findall(r"[A-ZÁÉÍÓÚÑÜ]{2,}", text or "")) or None


def _limpiar_numero_documento(raw_text):
    digitos = re.sub(r"\D", "", raw_text or "")
    if not digitos:
        return None
    inv = digitos[::-1]
    agrupado = ".".join(inv[i : i + 3] for i in range(0, len(inv), 3))
    return agrupado[::-1]


def extract_dni(pdf_path):
    campos = {
        "DNI - Apellido": None,
        "DNI - Nombre": None,
        "DNI - Fecha de nacimiento": None,
        "DNI - Documento N°": None,
    }

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        im = page.to_image(resolution=RESOLUTION).original

        ocr_data = pytesseract.image_to_data(im, lang="spa", output_type=pytesseract.Output.DICT)
        lines = _group_lines(ocr_data)

        idx = _find_caption(lines, "Apellido")
        campos["DNI - Apellido"] = _solo_letras(_value_line(lines, idx))

        idx = _find_caption(lines, "Nombre")
        campos["DNI - Nombre"] = _solo_letras(_value_line(lines, idx))

        idx = _find_caption(lines, "Fecha", "nacimiento")
        val = _value_line(lines, idx)
        if val:
            tokens = val.split()
            if len(tokens) >= 4:
                dia, mes, _mes_en, anio = tokens[0], tokens[1], tokens[2], tokens[-1]
                mes = re.sub(r"[^A-Z]", "", mes)
                if dia.isdigit() and anio.isdigit() and mes:
                    campos["DNI - Fecha de nacimiento"] = f"{dia} {mes} {anio}"

        # Recorte fijo (ver docstring) para el N° de Documento: esquina
        # inferior izquierda de la tarjeta, como fracción de la imagen.
        w, h = im.size
        recorte = im.crop((0, int(h * 0.907), int(w * 0.376), h)).convert("L")
        recorte = ImageOps.autocontrast(recorte)
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789."
        raw_num = pytesseract.image_to_string(recorte, lang="eng", config=cfg)
        campos["DNI - Documento N°"] = _limpiar_numero_documento(raw_num)

    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_dni.py <ruta_al_pdf>")
        sys.exit(1)
    campos = extract_dni(sys.argv[1])
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
