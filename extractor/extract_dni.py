"""
Extractor real del DNI (frente + dorso), con OCR (Tesseract vía pytesseract),
SIN IA de interpretación -- el OCR solo convierte píxeles en texto, después
se lee por posición/etiqueta igual que en extract_solicitud.py / extract_aval.py.

ESTADO (2026-08-11): calibrado contra 4 DNI reales, no solo 1 -- el primer
ejemplo (pdfs-prueba/DNI PAZ, AGUSTIN.pdf) es una foto de buena calidad y
funcionaba perfecto, pero contra 3 DNI reales más (pdfs-prueba/05. DNI
BUSQUIN OSCAR ALBERTO 1.pdf, DNI MARIA MERCEDES FALU.pdf, DNI DE
MONASTERIO.pdf) el extractor viejo fallaba casi todos los campos -- no por
un bug de lógica, sino porque esas fotos/escaneos son de resolución/calidad
bastante más baja y el OCR crudo no las leía bien. Dos cambios de fondo:

1. PREPROCESADO de imagen antes del OCR de las etiquetas impresas (upscale
   2x + escala de grises + autocontraste + nitidez) -- mejora mucho la
   lectura en fotos borrosas/de baja resolución. Confirmado con los 4
   ejemplos reales.
2. El MRZ (las 3 líneas de código de máquina en la parte de abajo del
   dorso, formato ICAO 9303 TD1) se lee MUCHO más limpio que el texto
   impreso en TODOS los ejemplos que sí lo tienen -- es una fuente más
   confiable para Documento/Fecha de nacimiento/Apellido/Nombre que las
   etiquetas bilingües del frente, así que se usa como fuente PRIMARIA
   (con el crop especial del frente y las etiquetas impresas como
   respaldo). OJO: el MRZ mejora si se lee a resolución nativa, SIN el
   preprocesado de arriba -- el upscale+nitidez rompe el tipo de letra
   angosto del MRZ en vez de ayudarlo. Por eso son dos pasadas de OCR
   distintas, no una sola.

DNI DE MONASTERIO.pdf es además un formato VIEJO ("libreta" rectangular,
sin bordes redondeados) que ni siquiera tiene MRZ -- ahí no queda otra que
las etiquetas impresas ("APELLIDO/S" en mayúsculas fijas, no bilingüe
"Apellido / Surname" como el formato nuevo). El matching de etiquetas ahora
es insensible a mayúsculas/acentos para cubrir ambos formatos con el mismo
código.

CAMPOS NUEVOS (Domicilio, Lugar de nacimiento, CUIL) salen del DORSO, en el
mismo bloque de texto que tapa parcialmente el patrón de seguridad -- best
effort, calidad variable según la foto (confirmado: en 2 de los 4 ejemplos
reales el CUIL se lee bien, en los otros 2 no aparece nítido con ninguna
combinación de OCR probada). Si no se encuentra, queda en None -- no se
inventa ni se calcula.

Uso:
    python3 extract_dni.py "../pdfs-prueba/DNI PAZ, AGUSTIN.pdf"
"""

import json
import os
import re
import sys

import pdfplumber
import pytesseract
from PIL import ImageFilter, ImageOps

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESSDATA_DIR = os.path.join(_HERE, "tessdata")
os.environ.setdefault("TESSDATA_PREFIX", _TESSDATA_DIR)

_TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(_TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

RESOLUTION = 300
LINE_TOLERANCE = 25  # px -- más ancho que en pdf_layout.py porque las cajas de OCR son más ruidosas que el texto nativo del PDF

MESES_NUM_A_ABREV = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC",
}


def _preprocesar(im):
    """Upscale 2x + gris + autocontraste + nitidez -- mejora mucho la
    lectura de las etiquetas impresas en fotos borrosas/de baja resolución.
    NO usar esto para leer el MRZ (ver docstring del módulo)."""
    w, h = im.size
    im2 = im.resize((w * 2, h * 2)).convert("L")
    im2 = ImageOps.autocontrast(im2)
    return im2.filter(ImageFilter.SHARPEN)


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


def _lineas_ocr(im, psm=None):
    config = f"--psm {psm}" if psm else ""
    ocr_data = pytesseract.image_to_data(im, lang="spa", config=config, output_type=pytesseract.Output.DICT)
    return _group_lines(ocr_data)


def _normalizar(s):
    return (s or "").upper().replace("Í", "I").replace("Ó", "O").replace("Á", "A").replace("É", "E").replace("Ú", "U")


def _find_caption(lines, *fragments, start=0):
    """Igual que antes, pero insensible a mayúsculas/acentos -- así matchea
    tanto 'Apellido / Surname' (formato nuevo) como 'APELLIDO/S' (formato
    viejo, libreta) con el mismo fragmento de búsqueda."""
    fragments_norm = [_normalizar(f) for f in fragments]
    for i in range(start, len(lines)):
        text = _normalizar(lines[i]["text"])
        if all(f in text for f in fragments_norm):
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


def _formatear_numero_documento(digitos):
    if not digitos:
        return None
    inv = digitos[::-1]
    agrupado = ".".join(inv[i : i + 3] for i in range(0, len(inv), 3))
    return agrupado[::-1]


def _anio_completo(yy):
    """MRZ solo trae el año con 2 dígitos -- asume 19XX salvo que sea menor
    o igual al año actual de 2 dígitos (en cuyo caso podría ser 20XX,
    ej. un titular nacido en 2015)."""
    import datetime

    actual_2d = datetime.date.today().year % 100
    return 2000 + yy if yy <= actual_2d else 1900 + yy


def _parsear_mrz(texto):
    """Extrae Documento/Fecha de nacimiento/Apellido/Nombre de las 3 líneas
    de MRZ (formato ICAO 9303 TD1), si están presentes -- mucho más
    confiable que las etiquetas impresas cuando la foto es de baja calidad
    (ver docstring del módulo). Devuelve un dict, con None en lo que no se
    pudo leer."""
    resultado = {"documento": None, "fecha_nacimiento": None, "apellido": None, "nombre": None}

    m_doc = re.search(r"ID([A-Z]{3})(\d{6,9})", texto)
    if m_doc:
        resultado["documento"] = _formatear_numero_documento(m_doc.group(2))

    m_fecha = re.search(r"(\d{2})(\d{2})(\d{2})\d[MF](\d{6})\d([A-Z]{3})", texto)
    if m_fecha:
        yy, mm, dd = int(m_fecha.group(1)), int(m_fecha.group(2)), int(m_fecha.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            anio = _anio_completo(yy)
            mes_abrev = MESES_NUM_A_ABREV[mm]
            resultado["fecha_nacimiento"] = f"{dd:02d} {mes_abrev} {anio}"

    # Ojo: el patrón exige AL MENOS UNA letra real en cada grupo -- si se
    # permite "<" solo, matchea contra el relleno de "<<<<<..." de las
    # líneas 1/2 (que también contiene "<<" en algún punto) antes de llegar
    # a la línea 3 (nombre real), devolviendo basura.
    m_nombre = re.search(r"([A-Z]{2,}(?:<[A-Z]+)*)<<([A-Z]{2,}(?:<[A-Z]+)*)", texto)
    if m_nombre:
        apellido = m_nombre.group(1).replace("<", " ").strip()
        nombre = m_nombre.group(2).replace("<", " ").strip()
        if apellido:
            resultado["apellido"] = apellido
        if nombre:
            resultado["nombre"] = nombre

    return resultado


def _extraer_domicilio_lugar_cuil(lineas_variantes):
    """Busca DOMICILIO / LUGAR DE NACIMIENTO (o "FECHA Y LUGAR DE
    NACIMIENTO", formato viejo que junta ambos datos en un solo campo) /
    CUIL en el dorso -- busca en varias pasadas de OCR (`lineas_variantes`,
    una lista de listas de líneas) y se queda con el primer resultado que
    encuentre en cualquiera de ellas, porque ninguna pasada sola lee bien
    los 4 ejemplos reales disponibles (ver docstring del módulo)."""
    domicilio = lugar_nacimiento = cuil = None

    for lineas in lineas_variantes:
        if domicilio is None:
            idx = _find_caption(lineas, "DOMICILIO")
            if idx is not None:
                texto = lineas[idx]["text"]
                m = re.search(r"DOMICILIO[:\s]+(.+)", texto, re.IGNORECASE)
                valor = m.group(1).strip() if m else None
                # el domicilio suele partirse en 2 líneas de OCR -- se pega
                # la siguiente línea si no es ya la de "lugar de nacimiento"
                if valor and idx + 1 < len(lineas):
                    siguiente = lineas[idx + 1]["text"]
                    if "NACIMIENTO" not in _normalizar(siguiente) and "CUIL" not in _normalizar(siguiente):
                        valor = f"{valor} {siguiente}".strip()
                if valor:
                    domicilio = valor

        if lugar_nacimiento is None:
            idx = _find_caption(lineas, "LUGAR", "NACIMIENTO")
            if idx is not None:
                texto = lineas[idx]["text"]
                candidato = None
                if "FECHA" in _normalizar(texto):
                    # Formato viejo: "FECHA Y LUGAR DE NACIMIENTO: <fecha>"
                    # -- lo que sigue en la misma línea es la FECHA, el
                    # lugar viene en la línea SIGUIENTE (ej. "- SALTA").
                    if idx + 1 < len(lineas):
                        candidato = lineas[idx + 1]["text"].strip(" -")
                        if "CUIL" in _normalizar(candidato):
                            candidato = None
                else:
                    m = re.search(r"NACIMIENTO[:\s]+(.+)", texto, re.IGNORECASE)
                    if m:
                        candidato = m.group(1).strip()
                if candidato:
                    # un nombre de lugar es solo texto -- corta en el
                    # primer dígito (ruido de OCR que se cuela al final).
                    candidato = re.split(r"\d", candidato)[0].strip(" -")
                    if candidato:
                        lugar_nacimiento = candidato

        if cuil is None:
            idx = _find_caption(lineas, "CUIL")
            if idx is not None:
                texto = lineas[idx]["text"]
                m = re.search(r"CUIL[/A-Z]*[:\s]+([\d.-]{10,15})", texto, re.IGNORECASE)
                if m:
                    cuil = m.group(1).strip(" .-") and re.sub(r"[^\d-]", "", m.group(1))

        if domicilio and lugar_nacimiento and cuil:
            break

    return domicilio, lugar_nacimiento, cuil


def extract_dni(pdf_path):
    campos = {
        "DNI - Apellido": None,
        "DNI - Nombre": None,
        "DNI - Fecha de nacimiento": None,
        "DNI - Documento N°": None,
        "DNI - Domicilio": None,
        "DNI - Lugar de nacimiento": None,
        "DNI - CUIL": None,
    }

    with pdfplumber.open(pdf_path) as pdf:
        page0 = pdf.pages[0]
        im0 = page0.to_image(resolution=RESOLUTION).original

        # --- MRZ del dorso PRIMERO -- es la fuente MÁS confiable de
        # Documento/Fecha/Apellido/Nombre (ver docstring del módulo), así
        # que se usa como base y el frente solo completa lo que falte. ---
        mrz = {"documento": None, "fecha_nacimiento": None, "apellido": None, "nombre": None}
        if len(pdf.pages) > 1:
            page1 = pdf.pages[1]
            im1 = page1.to_image(resolution=RESOLUTION).original
            texto_mrz = pytesseract.image_to_string(im1, lang="spa")
            mrz = _parsear_mrz(texto_mrz)

        campos["DNI - Documento N°"] = mrz["documento"]
        campos["DNI - Fecha de nacimiento"] = mrz["fecha_nacimiento"]
        campos["DNI - Apellido"] = mrz["apellido"]
        campos["DNI - Nombre"] = mrz["nombre"]

        # --- Respaldo por etiqueta impresa del frente, para lo que el MRZ
        # no trajo (documentos sin MRZ, formato viejo "libreta", o MRZ mal
        # leído) -- recorte especial para Documento N° (zona con textura de
        # seguridad) y OCR normal + preprocesado para el resto. ---
        if not campos["DNI - Documento N°"]:
            w, h = im0.size
            recorte = im0.crop((0, int(h * 0.907), int(w * 0.376), h)).convert("L")
            recorte = ImageOps.autocontrast(recorte)
            cfg = "--psm 7 -c tessedit_char_whitelist=0123456789."
            raw_num = pytesseract.image_to_string(recorte, lang="eng", config=cfg)
            campos["DNI - Documento N°"] = _limpiar_numero_documento(raw_num)

        if not campos["DNI - Apellido"] or not campos["DNI - Nombre"] or not campos["DNI - Fecha de nacimiento"]:
            lineas_frente = _lineas_ocr(im0)
            lineas_frente_preprocesado = _lineas_ocr(_preprocesar(im0), psm=6)

            if not campos["DNI - Apellido"]:
                idx = _find_caption(lineas_frente, "Apellido")
                fuente = lineas_frente
                if idx is None:
                    idx = _find_caption(lineas_frente_preprocesado, "Apellido")
                    fuente = lineas_frente_preprocesado
                campos["DNI - Apellido"] = _solo_letras(_value_line(fuente, idx))

            if not campos["DNI - Nombre"]:
                idx = _find_caption(lineas_frente, "Nombre")
                fuente = lineas_frente
                if idx is None:
                    idx = _find_caption(lineas_frente_preprocesado, "Nombre")
                    fuente = lineas_frente_preprocesado
                campos["DNI - Nombre"] = _solo_letras(_value_line(fuente, idx))

            if not campos["DNI - Fecha de nacimiento"]:
                idx = _find_caption(lineas_frente, "Fecha", "nacimiento")
                val = _value_line(lineas_frente, idx)
                if val:
                    tokens = val.split()
                    if len(tokens) >= 4:
                        dia, mes, _mes_en, anio = tokens[0], tokens[1], tokens[2], tokens[-1]
                        mes = re.sub(r"[^A-Z]", "", mes)
                        if dia.isdigit() and anio.isdigit() and mes:
                            campos["DNI - Fecha de nacimiento"] = f"{dia} {mes} {anio}"

        # --- Domicilio / Lugar de nacimiento / CUIL: solo están en el
        # dorso, best effort (ver docstring del módulo). ---
        if len(pdf.pages) > 1:
            lineas_dorso = _lineas_ocr(im1)
            lineas_dorso_preprocesado = _lineas_ocr(_preprocesar(im1), psm=6)
            # Preprocesada primero -- en los ejemplos reales calibrados
            # (ver docstring) da resultados más limpios para este bloque de
            # texto que la pasada sin procesar.
            domicilio, lugar_nac, cuil = _extraer_domicilio_lugar_cuil(
                [lineas_dorso_preprocesado, lineas_dorso]
            )
            campos["DNI - Domicilio"] = domicilio
            campos["DNI - Lugar de nacimiento"] = lugar_nac
            campos["DNI - CUIL"] = cuil

    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_dni.py <ruta_al_pdf>")
        sys.exit(1)
    campos = extract_dni(sys.argv[1])
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
