"""
Utilidades de bajo nivel para leer un PDF de SOLICITUD por coordenadas
(sin IA / sin LLM). Agrupa palabras en "líneas" usando su coordenada
vertical (top), tolerando el pequeño desfasaje que introduce Zurich al
tipear el valor sobre el renglón impreso (unos 2-4pt de diferencia).

Uso típico:
    from pdf_layout import load_lines
    pages = load_lines("pdfs-prueba/SOLICITUD.pdf")
    # pages[0] es la lista de líneas de la página 0
    # cada línea es un dict: {"top": float, "words": [...], "text": str}
    # cada word es el dict que devuelve pdfplumber.extract_words()
"""

import pdfplumber

# Tolerancia vertical (en puntos PDF) para considerar que dos palabras
# están en el mismo renglón visual del formulario.
LINE_TOLERANCE = 4.0


def group_words_into_lines(words, tolerance=LINE_TOLERANCE):
    """Agrupa una lista de words (de una sola página) en líneas.

    Cada línea resultante trae sus words ordenadas por x0 (izquierda a
    derecha) y un campo 'text' con el texto concatenado, útil para
    búsquedas rápidas con `in`.
    """
    words_sorted = sorted(words, key=lambda w: w["top"])
    lines = []
    for w in words_sorted:
        placed = False
        for line in lines:
            if abs(line["top"] - w["top"]) <= tolerance:
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


def load_lines(pdf_path):
    """Devuelve una lista (una entrada por página) de líneas agrupadas."""
    pages_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            pages_lines.append(group_words_into_lines(words))
    return pages_lines


def find_line(lines, contains, start=0):
    """Busca la primera línea (desde el índice start) cuyo texto contenga
    todos los fragmentos de `contains` (str o lista de str)."""
    if isinstance(contains, str):
        contains = [contains]
    for i in range(start, len(lines)):
        text = lines[i]["text"]
        if all(c in text for c in contains):
            return i
    return None


def word_x0(line, text):
    """x0 (borde izquierdo) de la primera word cuyo texto sea exactamente
    `text` en la línea. None si no está."""
    return next((w["x0"] for w in line["words"] if w["text"] == text), None)


def word_x1(line, text):
    """x1 (borde derecho) de la primera word cuyo texto sea exactamente
    `text` en la línea. None si no está. Usar esto (no x0 + un número
    fijo) como límite izquierdo al leer el valor que sigue a una
    etiqueta: cada palabra ya trae su propio ancho real (w['x1'])."""
    return next((w["x1"] for w in line["words"] if w["text"] == text), None)


def value_between(line, x_start, x_end):
    """Concatena el texto de las words de una línea cuyo x0 cae dentro
    de [x_start, x_end). Sirve para leer el valor tipeado entre dos
    etiquetas (captions) conocidas."""
    words = [w for w in line["words"] if x_start <= w["x0"] < x_end]
    return " ".join(w["text"] for w in words).strip()


def checkbox_marked(line, label_x0, x_lookback=25):
    """Determina si el checkbox asociado a una etiqueta ubicada en
    label_x0 está marcado. En los PDF de Zurich la marca es una 'X'
    tipeada inmediatamente antes (a la izquierda) de la palabra de la
    etiqueta, típicamente entre 5 y 20pt antes.

    Devuelve "Marcado" / "No marcado".
    """
    for w in line["words"]:
        if w["text"] == "X" and 0 < (label_x0 - w["x0"]) <= x_lookback:
            return "Marcado"
    return "No marcado"


def nearest_checkbox_label(line, x_candidates):
    """Para líneas con varias opciones de checkbox en la misma fila
    (ej. IVA: Resp. Insc. / No Gravado / Exento / Cons. Final /
    Monotributista), busca cada 'X' de la línea y la asigna a la
    etiqueta cuyo x0 sea el siguiente inmediato a la derecha.

    x_candidates: lista de (nombre_campo, x0_de_la_etiqueta)
    Devuelve un dict {nombre_campo: "Marcado"/"No marcado"}.
    """
    result = {name: "No marcado" for name, _ in x_candidates}
    xs_words = [w for w in line["words"] if w["text"] == "X"]
    for xw in xs_words:
        best = None
        best_dist = None
        for name, x0 in x_candidates:
            dist = x0 - xw["x0"]
            if 0 < dist and (best_dist is None or dist < best_dist):
                best = name
                best_dist = dist
        if best is not None:
            result[best] = "Marcado"
    return result
