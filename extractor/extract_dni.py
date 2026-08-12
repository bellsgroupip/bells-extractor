"""
Extractor real del DNI (frente + dorso), con OCR (Tesseract vía pytesseract),
SIN IA de interpretación -- el OCR solo convierte píxeles en texto, después
se lee por posición/etiqueta igual que en extract_solicitud.py / extract_aval.py.

ESTADO (2026-08-12): calibrado contra 13 DNI reales de varios formatos y
calidades (no solo fotos prolijas) -- pdfs-prueba/ tiene el detalle
completo. Cambios de fondo, en orden de cuándo se agregaron:

1. PREPROCESADO de imagen antes del OCR de las etiquetas impresas (upscale
   2x + escala de grises + autocontraste + nitidez) -- mejora mucho la
   lectura en fotos borrosas/de baja resolución.
2. El MRZ (las 3 líneas de código de máquina, formato ICAO 9303 TD1) se
   lee MUCHO más limpio que el texto impreso en la mayoría de los
   ejemplos que sí lo tienen -- es la fuente PRIMARIA para Documento/
   Fecha de nacimiento/Apellido/Nombre (con el crop especial del frente y
   las etiquetas impresas como respaldo). El MRZ mejora si se lee a
   resolución nativa, SIN el preprocesado de arriba -- el upscale+nitidez
   rompe el tipo de letra angosto del MRZ en vez de ayudarlo. Por eso son
   pasadas de OCR distintas, no una sola.
3. El MRZ normalmente está en el DORSO, pero algunos formatos viejos
   ("tarjeta" primera generación, ~2011) lo traen en el FRENTE en vez del
   dorso (el dorso de esos tiene código de barras 2D en lugar de MRZ) --
   se prueban ambas páginas, completando solo los campos que falten (no
   se pisa lo que ya se encontró). También se prueba el dorso con
   "--psm 6" si el modo automático no encuentra nada -- en dorsos muy
   cargados de gráficos (foto + holograma + huella + código de barras) el
   PSM automático a veces IGNORA el bloque de MRZ directamente, ni
   siquiera lo lee mal.
4. Fecha de nacimiento: se cruza SIEMPRE contra la etiqueta impresa del
   frente ("Fecha de nacimiento / Date of birth", formato RENAPER
   ~2021+), incluso cuando el MRZ ya trajo un valor -- un solo dígito mal
   leído del MRZ da una fecha con formato válido pero incorrecta (ej. año
   "26" en vez de "96" en un ejemplo real), y no hay forma de detectarlo
   mirando solo el MRZ. Si hay desacuerdo, gana la etiqueta impresa. Una
   fecha resultante POSTERIOR a hoy se descarta directamente (nadie firma
   un DNI antes de nacer) -- red de seguridad mínima, no filtra todos los
   casos (una fecha errónea pero no futura puede colarse igual si ni el
   MRZ ni la etiqueta la corrigen).

El formato "libreta" viejo (rectangular, sin bordes redondeados, sin MRZ
en ninguna página) sigue sin extraer Apellido/Nombre/Documento de forma
confiable -- solo se pudo calibrar 1 ejemplo real de este formato
específico.

CAMPOS Domicilio/Lugar de nacimiento/CUIL salen del DORSO, en el mismo
bloque de texto que tapa parcialmente una marca de agua de seguridad
(holograma/retrato con textura de rayado) -- best effort, calidad muy
variable según la foto. Domicilio se recupera en la mayoría de los DNI
con MRZ calibrados (aislando el canal ROJO de la imagen para atenuar la
marca de agua -- ver _extraer_domicilio_lugar_watermark), pero Lugar de
Nacimiento sigue siendo el campo más frágil (esa etiqueta específica cae
justo sobre la parte más densa de la marca de agua en varios ejemplos
reales) -- si no se encuentra queda en None, no se inventa ni se calcula.

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
            # Una fecha de nacimiento futura es imposible -- si el cálculo
            # de siglo (o un dígito mal leído del MRZ) da una fecha
            # posterior a hoy, mejor no devolver nada que devolver un dato
            # con sentido (ej. "nacido en 2026" para un titular adulto,
            # visto en un ejemplo real 2026-08-12: el MRZ traía un dígito
            # OCR mal leído en el año de nacimiento).
            import datetime

            try:
                fecha_calculada = datetime.date(anio, mm, dd)
            except ValueError:
                fecha_calculada = None
            if fecha_calculada and fecha_calculada <= datetime.date.today():
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


def _calidad_texto(s, min_letras):
    """Puntaje de qué tan "limpio" parece un texto de OCR -- se usa para
    elegir, entre varias pasadas de OCR con distinto preprocesado, cuál
    devolvió el mejor resultado (no hay ground truth en producción, así
    que la única señal disponible es qué tan plausible es el texto en sí:
    mayoría de letras, poco ruido de símbolos/dígitos sueltos, y no
    empieza con puntuación -- eso evita aceptar basura tipo '457 - " | h n
    q' o un fragmento cortado tipo '- DE: TUCUMAN' solo porque matcheó la
    etiqueta en esa línea)."""
    if not s:
        return -1
    if not s[0].isalnum():
        return -1
    letras = sum(1 for c in s if c.isalpha())
    if letras < min_letras:
        return -1
    otros = sum(1 for c in s if not c.isalpha() and not c.isspace())
    total = letras + otros
    if total and (otros / total) > 0.25:
        return -1
    return letras - otros


def _extraer_domicilio_lugar_watermark(im1):
    """Extrae DOMICILIO / LUGAR DE NACIMIENTO del bloque superior-izquierdo
    del dorso (formato nuevo, con MRZ) -- ese bloque está impreso ENCIMA de
    una marca de agua de seguridad (retrato/holograma con textura de
    rayado o manchas de color), que rompe el OCR de `_lineas_ocr` normal en
    la mayoría de los DNI reales calibrados (2026-08-12): el texto es
    legible a simple vista pero el ruido de fondo confunde a Tesseract.

    Mitigación: aislar el canal ROJO de la imagen (el fondo suele ser
    azul/celeste -- en el canal rojo queda mucho más claro que el texto
    negro, que es oscuro en los 3 canales) y probar unas pocas
    combinaciones de threshold/tamaño de recorte, quedándose con la de
    mejor `_calidad_texto` para cada campo (domicilio y lugar de
    nacimiento se evalúan por separado -- pueden salir mejor en pasadas
    distintas). Sigue siendo best-effort: en fotos con la marca de agua
    muy densa justo sobre el texto puede no recuperar nada limpio (ver
    docstring del módulo)."""
    w, h = im1.size
    mejor_domicilio = {"valor": None, "calidad": -1}
    mejor_lugar = {"valor": None, "calidad": -1}

    for hfrac in (0.23, 0.30):
        crop = im1.crop((0, int(h * 0.03), int(w * 0.82), int(h * hfrac)))
        canal_rojo, _, _ = crop.split()
        rojo_autoc = ImageOps.autocontrast(canal_rojo)
        ampliada = rojo_autoc.resize((rojo_autoc.width * 2, rojo_autoc.height * 2))

        for umbral in (None, 90, 100, 110):
            imagen_final = ampliada if umbral is None else ampliada.point(
                lambda p, umbral=umbral: 255 if p > umbral else 0
            )
            # image_to_string (no image_to_data/_lineas_ocr) a propósito acá:
            # el algoritmo de reading-order propio de Tesseract separa las 3
            # líneas del bloque bastante mejor que agrupar por coordenada
            # "top" con tolerancia fija (que en este recorte, ampliado 2x,
            # a veces mezcla el orden de las líneas) -- confirmado
            # empíricamente contra los ejemplos reales calibrados.
            texto = pytesseract.image_to_string(imagen_final, lang="spa", config="--psm 6")
            lineas_texto = [l for l in texto.split("\n") if l.strip()]

            domicilio = None
            for i, linea in enumerate(lineas_texto):
                if "DOMICIL" not in _normalizar(linea):
                    continue
                m = re.search(r"DOMICILI[A-Z]*[:\s]+(.+)", linea, re.IGNORECASE)
                valor = m.group(1).strip(" -:.,") if m else None
                if valor and i + 1 < len(lineas_texto):
                    siguiente = lineas_texto[i + 1]
                    if "NACIM" not in _normalizar(siguiente) and "LUGAR" not in _normalizar(siguiente):
                        valor = f"{valor} {siguiente}".strip()
                domicilio = valor or None
                break
            calidad_dom = _calidad_texto(domicilio, min_letras=10)
            if calidad_dom > mejor_domicilio["calidad"]:
                mejor_domicilio = {"valor": domicilio, "calidad": calidad_dom}

            lugar_nacimiento = None
            for linea in lineas_texto:
                normalizada = _normalizar(linea)
                if "LUGAR" not in normalizada:
                    continue
                # "NACIMIENTO" rara vez sobrevive completo al OCR sobre la
                # marca de agua (ej. "NAQUIERIO", "NAGIENIS", "NABRRENTO")
                # -- en vez de exigir el substring exacto "NACIM", alcanza
                # con una palabra que empiece "NA" y tenga longitud
                # parecida, para no perder el resto del renglón (el valor
                # real) solo porque la etiqueta se leyó mal.
                m_etiqueta = re.search(r"NA[A-Z]{4,}", normalizada)
                if not m_etiqueta:
                    continue
                # _normalizar no cambia la longitud del texto (solo
                # mayúsculas/acentos), así que el índice del match vale
                # igual sobre la línea original.
                resto = linea[m_etiqueta.end():].strip(" :-.,")
                # Saca basura suelta de OCR pegada al final (símbolos que
                # no son letra/dígito/espacio, ej. un "�" residual).
                resto = re.sub(r"[^\w]+$", "", resto, flags=re.UNICODE)
                # OJO: NO cortar en el primer dígito -- el OCR a veces
                # confunde la PRIMERA letra del lugar con un dígito
                # (ej. "SALTA" leído "0ALTA"), y cortar ahí perdía el
                # valor entero. El filtro de ruido lo hace
                # _calidad_texto (por proporción, no por posición).
                lugar_nacimiento = resto or None
                break
            calidad_lugar = _calidad_texto(lugar_nacimiento, min_letras=3)
            if calidad_lugar > mejor_lugar["calidad"]:
                mejor_lugar = {"valor": lugar_nacimiento, "calidad": calidad_lugar}

        # Corte anticipado: si ya salió algo razonablemente limpio para
        # los 2 campos, no vale la pena seguir probando más variantes.
        if mejor_domicilio["calidad"] >= 15 and mejor_lugar["calidad"] >= 3:
            break

    return mejor_domicilio["valor"], mejor_lugar["valor"]


def _unir_lineas_mrz(texto):
    """Antes de correr el regex de MRZ, pega a cada línea de MRZ (la que
    tiene la tira de "<<<<") la línea anterior SI esa línea anterior es
    corta y solo letras -- el OCR a veces corta la 3ra línea del MRZ
    (apellido<<nombre) justo después del prefijo "DE"/"VAN"/etc. de un
    apellido compuesto, dejándolo en su propio renglón separado por un
    salto de línea que el regex de _parsear_mrz no cruza (ej. un DNI real
    calibrado 2026-08-12 partió "DE<MONASTERIO<<DIEGO<JOSE<<<<<" en "DE" +
    "<MONASTERIO<<DIEGO<JOSE<<<<<")."""
    lineas = texto.split("\n")
    resultado = []
    for i, linea in enumerate(lineas):
        limpia = linea.strip()
        if "<<<<" in limpia:
            # El MRZ real no tiene espacios -- un espacio suelto ahí es
            # ruido de OCR (ej. "DE <MONASTERIO<<..." en vez de
            # "DE<MONASTERIO<<...").
            limpia = limpia.replace(" ", "")
            if i > 0:
                anterior = lineas[i - 1].strip()
                if anterior and len(anterior) <= 6 and re.fullmatch(r"[A-Z]+", anterior):
                    limpia = anterior + limpia
        resultado.append(limpia)
    return "\n".join(resultado)


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
            mrz = _parsear_mrz(_unir_lineas_mrz(texto_mrz))
            # El PSM automático (default) a veces directamente IGNORA el
            # bloque de MRZ en dorsos muy cargados de gráficos (foto +
            # holograma + huella + código de barras 2D, ver ejemplo real
            # calibrado 2026-08-12) -- ni siquiera lo intenta leer, no es
            # que lo lea mal. "--psm 6" (asume un solo bloque de texto
            # uniforme) sí lo encuentra en ese caso.
            if not all(mrz.values()):
                texto_mrz_psm6 = pytesseract.image_to_string(im1, lang="spa", config="--psm 6")
                mrz_psm6 = _parsear_mrz(_unir_lineas_mrz(texto_mrz_psm6))
                for campo, valor in mrz_psm6.items():
                    if not mrz[campo] and valor:
                        mrz[campo] = valor

        # Algunos DNI viejos (formato "tarjeta" de primera generación, sin
        # MRZ en el dorso -- llevan código de barras 2D en su lugar, ver
        # docstring del módulo) tienen el MRZ impreso en el FRENTE, debajo
        # de la foto, en vez del dorso. Si el dorso no lo trajo completo,
        # probar también el frente (con y sin preprocesado) y completar
        # SOLO lo que siga faltando -- no pisar lo que ya se encontró.
        if not all(mrz.values()):
            # Preprocesada primero -- en el ejemplo real calibrado da
            # apellido/nombre mucho más limpios que la pasada cruda (que
            # sí puede ganarle en Documento N°, por eso se prueban las 2 y
            # no se corta apenas la primera encuentra algo).
            for candidato_im in (_preprocesar(im0), im0):
                texto_mrz_frente = pytesseract.image_to_string(candidato_im, lang="spa")
                mrz_frente = _parsear_mrz(_unir_lineas_mrz(texto_mrz_frente))
                for campo, valor in mrz_frente.items():
                    if not valor:
                        continue
                    # apellido/nombre: no aceptar un match de 1-2 letras
                    # (mejor no tener nada que un valor obviamente cortado
                    # a la mitad por el OCR).
                    if campo in ("apellido", "nombre") and len(valor) < 3:
                        continue
                    if not mrz[campo]:
                        mrz[campo] = valor
                if all(mrz.values()):
                    break

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

        necesita_respaldo_frente = (
            not campos["DNI - Apellido"] or not campos["DNI - Nombre"] or not campos["DNI - Fecha de nacimiento"]
        )
        # Diseños nuevos de DNI (RENAPER, ~2021 en adelante) traen "Fecha
        # de nacimiento" bien grande e impresa en limpio en el frente,
        # SEPARADA de "Fecha de emisión"/"Fecha de vencimiento" -- vale la
        # pena cruzarla contra el MRZ aunque el MRZ ya haya traído un
        # valor, porque un solo dígito mal leído del MRZ (ej. año "26" en
        # vez de "96", visto en un ejemplo real 2026-08-12) da una fecha
        # con formato válido pero directamente incorrecta, y no hay forma
        # de detectar ese error solo mirando el MRZ.
        if necesita_respaldo_frente or campos["DNI - Fecha de nacimiento"]:
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

            # Solo "NACIM" (no también "Fecha") -- la palabra "Fecha" se lee
            # mal seguido (ej. "Eacha de nacimiento", la "F" confundida con
            # "E") pero "nacimiento" es una palabra que no aparece en
            # ninguna otra etiqueta del frente (a diferencia de "Fecha",
            # que también está en "Fecha de emisión"/"Fecha de
            # vencimiento"), así que alcanza como ancla única.
            idx = _find_caption(lineas_frente, "NACIM")
            fuente_fecha = lineas_frente
            if idx is None:
                idx = _find_caption(lineas_frente_preprocesado, "NACIM")
                fuente_fecha = lineas_frente_preprocesado
            val = _value_line(fuente_fecha, idx)
            fecha_frente = None
            if val:
                # Regex en vez de posición fija de tokens -- el renglón
                # trae basura de OCR variable alrededor (ej. comilla suelta
                # antes del día, o un token final tipo "A/O" después del
                # año que antes se tomaba por error como si fuera el año).
                m_dia = re.search(r"\b(\d{1,2})\b", val)
                # Substring, no límite de palabra -- el mes en español suele
                # salir pegado sin espacio a la abreviatura en inglés (ej.
                # "ABR�APR", con un caracter de reemplazo de por medio) y
                # un \b ahí no matchea.
                m_mes = re.search(r"(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)", val)
                m_anio = re.search(r"\b(\d{4})\b", val)
                if m_dia and m_mes and m_anio:
                    fecha_frente = f"{m_dia.group(1)} {m_mes.group(1)} {m_anio.group(1)}"
            if fecha_frente and fecha_frente != campos["DNI - Fecha de nacimiento"]:
                # Cuando hay desacuerdo entre MRZ y etiqueta impresa, se
                # prioriza la etiqueta -- ver comentario de arriba.
                campos["DNI - Fecha de nacimiento"] = fecha_frente
            elif not campos["DNI - Fecha de nacimiento"]:
                campos["DNI - Fecha de nacimiento"] = fecha_frente

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
            campos["DNI - CUIL"] = cuil

            # Domicilio/Lugar de nacimiento: la pasada de arriba casi nunca
            # los encuentra en fotos con marca de agua encima del texto
            # (formato nuevo, con MRZ) -- se prueba primero el aislamiento
            # de canal rojo (ver docstring de la función), y si no
            # encuentra nada se cae al resultado de la pasada de arriba
            # (que sigue siendo mejor para el formato viejo "libreta", sin
            # esa marca de agua).
            domicilio_wm, lugar_wm = _extraer_domicilio_lugar_watermark(im1)
            campos["DNI - Domicilio"] = domicilio_wm or domicilio
            campos["DNI - Lugar de nacimiento"] = lugar_wm or lugar_nac

    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_dni.py <ruta_al_pdf>")
        sys.exit(1)
    campos = extract_dni(sys.argv[1])
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
