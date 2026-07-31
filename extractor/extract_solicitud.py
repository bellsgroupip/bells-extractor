"""
Extractor real de la SOLICITUD Zurich, por coordenadas (pdfplumber),
SIN IA. Lee un PDF de solicitud y devuelve un dict con los campos del
Diccionario_Campos de /base/Base_Combinada_Solicitudes_Zurich.xlsx.

ESTADO ACTUAL (ver CLAUDE.md, punto 1 de "lo que falta"):
Implementados: Bloque 0 ("0. Documento" -- solo lo literal), Bloque 2
("2. SOLICITANTE / TOMADOR", 37 campos), Bloque 3 ("3. SOLICITANTE
CONJUNTO", 19 campos -- queda todo en None si la solicitud es de 1 vida),
Bloque 4 ("4. VIDA ASEGURADA 1" / Primera Vida Asegurada, 28 campos),
Bloque 4b ("4b. VIDA ASEGURADA 2" / Segunda Vida Asegurada, mismos 28
campos que el 4 -- también en None si es de 1 vida), Bloque 5
("5. Seguros existentes", 12 campos por Vida Asegurada), Bloque 6
("6/6b. Beneficios Options", 24 campos por Vida Asegurada -- SOLO pólizas
Options; Invest Future tiene su propia sección "6c", no implementada, y
queda todo en None), Bloque 7 ("7. Moneda/Inversión", 12 campos --
"Cuenta Individual" es de ambas familias, el resto exclusivo Invest
Future), Bloque 8 ("8. Prima", 19 campos -- Vanishing/Actualización son
de Options, Incremento anual es de Invest Future), Bloque 9
("9. Débito", 6 campos -- Tarjeta/CBU se derivan de cuál trae dígitos),
Bloque 10 ("10. BENEFICIARIOS PRINCIPALES", hasta 3, tabla por columnas)
y Bloque 11 ("11. BENEFICIARIOS CONTINGENTES", hasta 2 + checkboxes
Opción A/B). El resto de los bloques (Declaraciones/PEP, Privacidad,
Firmas) se agregan siguiendo el mismo patrón: reutilizar
pdf_layout.find_line / value_between / checkbox_marked /
nearest_checkbox_label sobre _flatten(pages) (no asumir un número de
página fijo: el mismo bloque cae
en distinta página según la plantilla -- Options 1 vida / 2 vidas /
Invest Future).

OJO -- hallazgo importante del Bloque 6: en 2 de los 3 PDF Options de
prueba, el título de esa sección viene con "Seguro" corrompido
("Beneficios Adicionales al Seg o de Vida..." -- falta "ur", glitch de
renderizado puntual de esos PDF). La Base_Combinada de referencia
tiene el MISMO hueco para esas 2 solicitudes (marca esos ~24 campos como
"N/A" aunque el PDF sí trae datos reales) -- quien haya armado esa
planilla probablemente pisó el mismo problema. Este extractor ya lo
resuelve con una búsqueda tolerante (regex), así que va a sacar más datos
de los que hoy figuran en Base_Combinada para esas 2 filas -- no es un
error del extractor, es la Base la que está incompleta ahí.

Campos NO extraíbles por coordenadas simples (quedan pendientes,
requieren una regla de negocio aparte, no un valor literal del PDF):
  - "Cantidad de vidas aseguradas": no aparece como campo explícito en
    ninguna página; se infiere contando si el bloque "Vida Asegurada 2"
    tiene datos cargados. Implementar una vez esté el extractor del
    Bloque 4b.
  - "Tomador distinto de la Vida Asegurada - Sí/No": con los Bloques 2 y 4
    ya andando, técnicamente se podría comparar
    "SOLICITANTE / TOMADOR - Nombre y Apellido" contra
    "VIDA ASEGURADA 1 - Nombre y Apellido" -- PERO en un ejemplo real de
    2 vidas (Zurich Options-AECLIF-1354029) la Base_Combinada marca este
    campo como "Sí" (distinto) aun cuando la Vida Asegurada 1 coincide
    con el Tomador, porque hay una Segunda Vida Asegurada (Solicitante
    Conjunto) que si difiere. No quedó claro con un solo ejemplo si la
    regla correcta es "compara contra CUALQUIER vida asegurada, no solo
    la 1" u otra cosa -- ver con Bells Group antes de implementarlo, para
    no adivinar una regla de negocio incorrecta.
  - "Tipo de firma": no hay una etiqueta "Firma manuscrita / digital"
    en el texto; hay que mirar la página de Firmas (14. Firma...) y
    decidir con qué criterio se clasifica (ej. presencia de imagen de
    firma vs. certificado digital). Queda para cuando se ataque el
    Bloque 14.

Uso:
    python3 extract_solicitud.py "../pdfs-prueba/Zurich Options-AECLIF-1354029.pdf"
"""

import json
import re
import sys

from pdf_layout import (
    load_lines,
    find_line,
    value_between,
    checkbox_marked,
    nearest_checkbox_label,
    word_x0,
    word_x1,
)


# Tolerancia horizontal al partir una fila de valores en columnas usando
# el x0 de las etiquetas de una fila de encabezado distinta (ej. "Manual %
# / No Manual %", "Actividad / Frecuencia"): el valor puede arrancar unos
# pocos puntos antes que su etiqueta de columna.
_COL_TOLERANCE = 5


def _flatten(pages):
    """Junta todas las páginas en una sola lista de líneas, en orden. Los
    bloques 3+ pueden caer en distinta página según la plantilla (Options 1
    vida / 2 vidas / Invest Future), así que en vez de indexar pages[N] a
    mano se busca el texto de la sección en esta lista completa."""
    return [line for page in pages for line in page]


def _parse_dni_cuit(text):
    """Lee 'DNI / L.C. / L.E. Nº <dni> C.U.I.T. / C.U.I.L. / C.D.I. Nº <cuit>'
    -- mismo patrón en los bloques 2, 3 y 4."""
    dni = cuit = None
    m = re.search(r"L\.E\.\s*Nº\s*([\d.]+)", text)
    if m:
        dni = m.group(1)
    m = re.search(r"C\.D\.I\.\s*Nº\s*([\d-]+)", text)
    if m:
        cuit = m.group(1)
    return dni, cuit


def _parse_fecha_nacimiento_sexo(line):
    """Lee 'Día D Mes M Año AAAA Sexo: ... Masculino ... Femenino' de una
    línea -- mismo patrón en los bloques 2, 3 y 4. Tolera que algún PDF
    tipee la fecha con espacios sueltos entre dígitos (ej. 'Mes 0 3' en vez
    de 'Mes 03', visto en VIDA ASEGURADA 1 de un ejemplo real) sacando los
    espacios internos de cada grupo antes de armar la fecha."""
    text = line["text"]
    fecha = None
    m = re.search(r"Día\s+([\d\s]+?)Mes\s+([\d\s]+?)Año\s+([\d\s]+?)Sexo", text)
    if m:
        dd, mm, yyyy = (g.replace(" ", "") for g in m.groups())
        if dd and mm and yyyy:
            fecha = f"{dd.zfill(2)}/{mm.zfill(2)}/{yyyy}"

    masc_x = fem_x = None
    for w in line["words"]:
        if w["text"] == "Masculino":
            masc_x = w["x0"]
        if w["text"] == "Femenino":
            fem_x = w["x0"]
    sexo_m = sexo_f = "No marcado"
    if masc_x is not None and fem_x is not None:
        marks = nearest_checkbox_label(line, [("Masculino", masc_x), ("Femenino", fem_x)])
        sexo_m, sexo_f = marks["Masculino"], marks["Femenino"]
    return fecha, sexo_m, sexo_f


def _value_after_label(line, label):
    """Devuelve el texto que sigue a una etiqueta en la misma línea.
    Normalmente la etiqueta es su propia 'word' (separada del valor por un
    espacio) y alcanza con word_x1 + value_between: pero en algunos
    renglones el PDF pega la etiqueta directo al valor sin espacio (ej.
    'nacimientoSALTA' o 'residenciaB° PRADERAS...' en vez de 'nacimiento
    SALTA' / 'residencia B° PRADERAS...'), y ahí hay que partir esa
    'word' fusionada a mano."""
    exact_end = word_x1(line, label)
    if exact_end is not None:
        return value_between(line, exact_end, 10_000)
    for w in line["words"]:
        if w["text"].startswith(label) and w["text"] != label:
            pegado = w["text"][len(label):]
            resto = value_between(line, w["x1"], 10_000)
            return f"{pegado} {resto}".strip() if resto else pegado
    return None


def _parse_si_no(line):
    """Determina cuál de las dos opciones 'Si'/'No' de una línea está
    marcada con una 'X' (mismo patrón de checkbox en varias preguntas del
    Bloque 4: actividad peligrosa, fumador, viajes al exterior)."""
    si_x = no_x = None
    for w in line["words"]:
        if w["text"] == "Si" and si_x is None:
            si_x = w["x0"]
        if w["text"] == "No" and no_x is None:
            no_x = w["x0"]
    if si_x is None or no_x is None:
        return "No marcado", "No marcado"
    marks = nearest_checkbox_label(line, [("Si", si_x), ("No", no_x)])
    return marks["Si"], marks["No"]


def _clean(s):
    s = (s or "").strip()
    return s if s else None


_LOWERCASE_ES = {"de", "del", "la", "las", "los", "y"}


def _titlecase_es(s):
    """Normaliza texto en MAYÚSCULA (como viene tipeado en el PDF) a estilo
    'Title Case' en español (igual convención que usa Base_Combinada), sin
    tocar valores que ya vengan con formato mixto (DNI, emails, etc.)."""
    s = _clean(s)
    if not s or not s.isupper():
        return s
    words = s.split(" ")
    out = []
    for i, w in enumerate(words):
        wl = w.lower()
        if i > 0 and wl in _LOWERCASE_ES:
            out.append(wl)
        else:
            # respeta abreviaturas con punto (ej. "B°") y capitaliza el resto
            out.append(wl[:1].upper() + wl[1:] if wl else wl)
    return " ".join(out)


# ---------------------------------------------------------------------
# Bloque 0. Documento
# ---------------------------------------------------------------------
def extract_bloque_0(pages):
    campos = {
        "N° de Solicitud / Póliza": None,
        "Fecha de solicitud": None,
        "Producto / Formulario": None,
        "Cantidad de vidas aseguradas": None,  # TODO: derivado (ver docstring)
        "Tomador distinto de la Vida Asegurada - Sí": "No marcado",  # TODO: derivado
        "Tomador distinto de la Vida Asegurada - No": "No marcado",  # TODO: derivado
        "Tipo de firma": None,  # TODO: derivado
    }

    page0 = pages[0]

    # Producto / Formulario: el encabezado de la portada dice literal
    # "Zurich Options" o "Zurich Invest Future" (en alguna de las primeras
    # líneas -- puede haber un renglón de DocuSign antes si el PDF es la
    # copia firmada). Las variantes más finas de la Base_Combinada ("Vida
    # Única" vs "Dos Vidas", "Joven", "Tomador distinto") NO están siempre
    # tipeadas en el PDF -- confirmado que "Joven" no aparece en ningún
    # lado del PDF de Invest Future Joven -- así que acá solo se distingue
    # la familia (Options / Invest Future), que sí es 100% literal.
    for line in page0[:5]:
        if line["text"].strip() in ("Zurich Options", "Zurich Invest Future"):
            campos["Producto / Formulario"] = line["text"].strip()
            break

    # Fecha de solicitud: línea "1. Introducción Día 09 Mes 01 Año 2025"
    idx = find_line(page0, ["Día", "Mes", "Año"])
    if idx is not None:
        line = page0[idx]
        m = re.search(
            r"Día\s+(\d{1,2})\s+Mes\s+(\d{1,2})\s+Año\s+(\d{4})", line["text"]
        )
        if m:
            dd, mm, yyyy = m.groups()
            campos["Fecha de solicitud"] = f"{dd.zfill(2)}/{mm.zfill(2)}/{yyyy}"

    # N° de Solicitud / Póliza: pie de página, línea corta tipo "1354029 1"
    for line in reversed(page0):
        m = re.fullmatch(r"(\d{5,8})\s+\d+", line["text"].strip())
        if m:
            campos["N° de Solicitud / Póliza"] = m.group(1)
            break

    return campos


# ---------------------------------------------------------------------
# Bloque 2. SOLICITANTE / TOMADOR
# ---------------------------------------------------------------------
def extract_bloque_2(pages):
    page0 = pages[0]
    campos = {}
    prefix = "SOLICITANTE / TOMADOR - "

    # --- Nombre y Apellido: según el PDF, el valor viene en la misma línea
    # que la etiqueta "Nombre y Apellido" (pegado a la derecha) o, si no hay
    # nada después de la etiqueta, en la línea siguiente.
    idx_seccion = find_line(page0, ["Datos del Solicitante"])
    idx_caption = find_line(
        page0, ["Nombre", "y", "Apellido"], start=idx_seccion or 0
    )
    nombre = None
    if idx_caption is not None:
        caption_line = page0[idx_caption]
        apellido_end = word_x1(caption_line, "Apellido")
        if apellido_end is not None:
            nombre = value_between(caption_line, apellido_end, 10_000)
        if not _clean(nombre) and idx_caption + 1 < len(page0):
            nombre = page0[idx_caption + 1]["text"]
    campos[prefix + "Nombre y Apellido"] = _clean(nombre)  # se deja tal cual (nombres van en mayúscula en la base también)

    # --- DNI / CUIT: misma línea, "Nº <dni> ... Nº <cuit>"
    idx = find_line(page0, ["DNI", "L.C.", "L.E.", "Nº"])
    dni, cuit = _parse_dni_cuit(page0[idx]["text"]) if idx is not None else (None, None)
    campos[prefix + "DNI / LC / LE"] = _clean(dni)
    campos[prefix + "CUIT / CUIL / CDI"] = _clean(cuit)

    # --- Fecha de nacimiento + Sexo
    idx = find_line(page0, ["Fecha", "de", "nacimiento", "Sexo"])
    if idx is not None:
        fecha_nac, sexo_m, sexo_f = _parse_fecha_nacimiento_sexo(page0[idx])
    else:
        fecha_nac, sexo_m, sexo_f = None, "No marcado", "No marcado"
    campos[prefix + "Fecha de nacimiento"] = fecha_nac
    campos[prefix + "Sexo - Masculino"] = sexo_m
    campos[prefix + "Sexo - Femenino"] = sexo_f

    # --- Nacionalidad / Lugar de nacimiento
    idx = find_line(page0, ["Nacionalidad", "Lugar", "de", "nacimiento"])
    nacionalidad = lugar_nac = None
    if idx is not None:
        line = page0[idx]
        nac_end = word_x1(line, "Nacionalidad")
        lugar_x0 = word_x0(line, "Lugar")
        if nac_end is not None and lugar_x0 is not None:
            nacionalidad = value_between(line, nac_end, lugar_x0)
        nacim_end = word_x1(line, "nacimiento")
        if nacim_end is not None:
            lugar_nac = value_between(line, nacim_end, 10_000)
    campos[prefix + "Nacionalidad"] = _clean(nacionalidad)
    campos[prefix + "Lugar de nacimiento"] = _titlecase_es(lugar_nac)

    # --- Estado civil / Actividad principal
    idx = find_line(page0, ["Estado", "civil", "Actividad", "principal"])
    estado_civil = actividad = None
    if idx is not None:
        line = page0[idx]
        civil_end = word_x1(line, "civil")
        actividad_x0 = word_x0(line, "Actividad")
        if civil_end is not None and actividad_x0 is not None:
            estado_civil = value_between(line, civil_end, actividad_x0)
        principal_end = word_x1(line, "principal")
        if principal_end is not None:
            actividad = value_between(line, principal_end, 10_000)
    campos[prefix + "Estado civil"] = _clean(estado_civil)
    campos[prefix + "Actividad principal"] = _titlecase_es(actividad)

    # --- Domicilio: Calle / Número / Piso / Dpto
    idx = find_line(page0, ["Domicilio:", "Calle"])
    calle = numero = piso = dpto = None
    if idx is not None:
        line = page0[idx]
        calle_end = word_x1(line, "Calle")
        nro_x0 = word_x0(line, "Nº")
        nro_end = word_x1(line, "Nº")
        piso_x0 = word_x0(line, "Piso")
        piso_end = word_x1(line, "Piso")
        dpto_word = next(
            (w for w in line["words"] if w["text"].startswith("Dpto")), None
        )
        dpto_x0 = dpto_word["x0"] if dpto_word else None
        dpto_end = dpto_word["x1"] if dpto_word else None
        if calle_end is not None and nro_x0 is not None:
            calle = value_between(line, calle_end, nro_x0)
        if nro_end is not None and piso_x0 is not None:
            numero = value_between(line, nro_end, piso_x0)
        if piso_end is not None and dpto_x0 is not None:
            piso = value_between(line, piso_end, dpto_x0)
        if dpto_end is not None:
            dpto = value_between(line, dpto_end, 10_000)
    campos[prefix + "Calle"] = _titlecase_es(calle)
    campos[prefix + "Número"] = _clean(numero)
    campos[prefix + "Piso"] = _clean(piso)
    campos[prefix + "Departamento"] = _clean(dpto)

    # --- Localidad / Provincia (primera aparición luego del domicilio principal)
    idx = find_line(page0, ["Localidad", "Provincia"], start=idx or 0)
    localidad = provincia = None
    if idx is not None:
        line = page0[idx]
        loc_end = word_x1(line, "Localidad")
        prov_x0 = word_x0(line, "Provincia")
        if loc_end is not None and prov_x0 is not None:
            localidad = value_between(line, loc_end, prov_x0)
        prov_end = word_x1(line, "Provincia")
        if prov_end is not None:
            provincia = value_between(line, prov_end, 10_000)
    campos[prefix + "Localidad"] = _titlecase_es(localidad)
    campos[prefix + "Provincia"] = _clean(provincia)

    # --- Código Postal / País
    idx = find_line(page0, ["Código", "Postal", "País"], start=idx or 0)
    cp = pais = None
    if idx is not None:
        line = page0[idx]
        postal_end = word_x1(line, "Postal")
        pais_x0 = word_x0(line, "País")
        if postal_end is not None and pais_x0 is not None:
            cp = value_between(line, postal_end, pais_x0)
        pais_end = word_x1(line, "País")
        if pais_end is not None:
            pais = value_between(line, pais_end, 10_000)
    campos[prefix + "Código Postal"] = _clean(cp)
    campos[prefix + "País"] = _clean(pais)

    # --- Tel. particular / Tel. celular
    idx = find_line(page0, ["Tel.", "particular"], start=idx or 0)
    tel_part = tel_cel = None
    if idx is not None:
        line = page0[idx]
        part_end = word_x1(line, "particular")
        tel2_x0 = None
        tel_words = [w for w in line["words"] if w["text"] == "Tel."]
        if len(tel_words) >= 2:
            tel2_x0 = tel_words[1]["x0"]
        if part_end is not None and tel2_x0 is not None:
            tel_part = value_between(line, part_end, tel2_x0)
        cel_end = word_x1(line, "celular")
        if cel_end is not None:
            tel_cel = value_between(line, cel_end, 10_000)
    campos[prefix + "Tel. particular"] = _clean(tel_part)
    campos[prefix + "Tel. celular"] = _clean(tel_cel)

    # --- E-mail
    idx = find_line(page0, ["E-mail"], start=idx or 0)
    email = None
    if idx is not None:
        line = page0[idx]
        email_end = word_x1(line, "E-mail")
        if email_end is not None:
            email = value_between(line, email_end, 10_000)
    campos[prefix + "E-mail"] = _clean(email)

    # --- Condición frente al IVA (5 checkboxes en una línea)
    idx = find_line(page0, ["Condición", "frente", "al", "I.V.A."])
    iva_marks = {
        "IVA - Responsable Inscripto": "No marcado",
        "IVA - No Gravado": "No marcado",
        "IVA - Exento": "No marcado",
        "IVA - Consumidor Final": "No marcado",
        "IVA - Monotributista": "No marcado",
    }
    if idx is not None:
        line = page0[idx]
        anchors = []
        for w in line["words"]:
            if w["text"] == "Insc.":
                anchors.append(("IVA - Responsable Inscripto", w["x0"]))
            elif w["text"] == "Gravado":
                anchors.append(("IVA - No Gravado", w["x0"]))
            elif w["text"] == "Exento":
                anchors.append(("IVA - Exento", w["x0"]))
            elif w["text"] == "Final":
                anchors.append(("IVA - Consumidor Final", w["x0"]))
            elif w["text"] == "Monotributista":
                anchors.append(("IVA - Monotributista", w["x0"]))
        if anchors:
            iva_marks = nearest_checkbox_label(line, anchors)
    for k, v in iva_marks.items():
        campos[prefix + k] = v

    # --- Domicilio para correspondencia: Particular / Otro / Indique cuál
    idx = find_line(page0, ["Particular", "Otro", "Indique", "cual"])
    corr_particular = corr_otro = "No marcado"
    indique_cual = None
    if idx is not None:
        line = page0[idx]
        anchors = []
        for w in line["words"]:
            if w["text"] == "Particular":
                anchors.append(("Correspondencia - Particular", w["x0"]))
            elif w["text"] == "Otro":
                anchors.append(("Correspondencia - Otro domicilio", w["x0"]))
        if anchors:
            marks = nearest_checkbox_label(line, anchors)
            corr_particular = marks["Correspondencia - Particular"]
            corr_otro = marks["Correspondencia - Otro domicilio"]
        cual_end = word_x1(line, "cual")
        if cual_end is not None:
            indique_cual = value_between(line, cual_end, 10_000)
    campos[prefix + "Correspondencia - Particular"] = corr_particular
    campos[prefix + "Correspondencia - Otro domicilio"] = corr_otro
    campos[prefix + "Correspondencia - Indique cuál"] = _clean(indique_cual)

    # --- Domicilio de correspondencia: Calle / Número / Piso / Dpto (2do bloque)
    idx2 = find_line(page0, ["Domicilio:", "Calle"], start=(idx or 0) + 1)
    corr_calle = corr_numero = corr_piso = corr_dpto = None
    if idx2 is not None:
        line = page0[idx2]
        calle_end = word_x1(line, "Calle")
        nro_x0 = word_x0(line, "Nº")
        nro_end = word_x1(line, "Nº")
        piso_x0 = word_x0(line, "Piso")
        piso_end = word_x1(line, "Piso")
        dpto_word = next(
            (w for w in line["words"] if w["text"].startswith("Dpto")), None
        )
        dpto_x0 = dpto_word["x0"] if dpto_word else None
        dpto_end = dpto_word["x1"] if dpto_word else None
        if calle_end is not None and nro_x0 is not None:
            corr_calle = value_between(line, calle_end, nro_x0)
        if nro_end is not None and piso_x0 is not None:
            corr_numero = value_between(line, nro_end, piso_x0)
        if piso_end is not None and dpto_x0 is not None:
            corr_piso = value_between(line, piso_end, dpto_x0)
        if dpto_end is not None:
            corr_dpto = value_between(line, dpto_end, 10_000)
    campos[prefix + "Correspondencia - Calle"] = _titlecase_es(corr_calle)
    campos[prefix + "Correspondencia - Número"] = _clean(corr_numero)
    campos[prefix + "Correspondencia - Piso"] = _clean(corr_piso)
    campos[prefix + "Correspondencia - Departamento"] = _clean(corr_dpto)

    # --- Localidad / Provincia / CP / País de correspondencia (2do bloque)
    idx3 = find_line(page0, ["Localidad", "Provincia"], start=(idx2 or 0) + 1)
    corr_localidad = corr_provincia = None
    if idx3 is not None:
        line = page0[idx3]
        loc_end = word_x1(line, "Localidad")
        prov_x0 = word_x0(line, "Provincia")
        if loc_end is not None and prov_x0 is not None:
            corr_localidad = value_between(line, loc_end, prov_x0)
        prov_end = word_x1(line, "Provincia")
        if prov_end is not None:
            corr_provincia = value_between(line, prov_end, 10_000)
    campos[prefix + "Correspondencia - Localidad"] = _titlecase_es(corr_localidad)
    campos[prefix + "Correspondencia - Provincia"] = _clean(corr_provincia)

    idx4 = find_line(page0, ["Código", "Postal", "País"], start=(idx3 or 0) + 1)
    corr_cp = corr_pais = None
    if idx4 is not None:
        line = page0[idx4]
        postal_end = word_x1(line, "Postal")
        pais_x0 = word_x0(line, "País")
        if postal_end is not None and pais_x0 is not None:
            corr_cp = value_between(line, postal_end, pais_x0)
        pais_end = word_x1(line, "País")
        if pais_end is not None:
            corr_pais = value_between(line, pais_end, 10_000)
    campos[prefix + "Correspondencia - Código Postal"] = _clean(corr_cp)
    campos[prefix + "Correspondencia - País"] = _clean(corr_pais)

    return campos


# ---------------------------------------------------------------------
# Bloque 3. SOLICITANTE CONJUNTO
# ---------------------------------------------------------------------
def extract_bloque_3(all_lines):
    """Mismo patrón que el Bloque 2, pero con menos campos: el
    Diccionario_Campos no separa el domicilio en Calle/Número/Piso/Dpto acá
    (un solo campo 'Domicilio completo'), ni desglosa las 5 opciones de
    I.V.A. (solo trackea si se marcó 'Consumidor Final'). No existe en las
    solicitudes de 1 vida (Options 1 vida / Invest Future) -- ahí todos
    estos campos quedan en None, que es lo correcto."""
    prefix = "SOLICITANTE CONJUNTO - "
    campos = {
        prefix + "Nombre y Apellido": None,
        prefix + "DNI": None,
        prefix + "CUIT": None,
        prefix + "Fecha de nacimiento": None,
        # Sexo/IVA quedan en None (no "No marcado") hasta confirmar que la
        # sección existe -- si la solicitud es de 1 vida no hay Solicitante
        # Conjunto y estos checkboxes no "no están marcados", directamente
        # no aplican.
        prefix + "Sexo - Masculino": None,
        prefix + "Sexo - Femenino": None,
        prefix + "Nacionalidad": None,
        prefix + "Lugar de nacimiento": None,
        prefix + "Estado civil": None,
        prefix + "Actividad principal": None,
        prefix + "Domicilio completo": None,
        prefix + "Localidad": None,
        prefix + "Provincia": None,
        prefix + "Código Postal": None,
        prefix + "País": None,
        prefix + "Tel. particular": None,
        prefix + "Tel. celular": None,
        prefix + "E-mail": None,
        prefix + "IVA - Consumidor Final": None,
    }

    idx_seccion = find_line(all_lines, ["Datos del Solicitante Conjunto"])
    if idx_seccion is None:
        return campos  # esta solicitud no tiene Solicitante Conjunto

    idx = find_line(all_lines, ["Nombre", "y", "Apellido"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        apellido_end = word_x1(line, "Apellido")
        if apellido_end is not None:
            campos[prefix + "Nombre y Apellido"] = _clean(value_between(line, apellido_end, 10_000))

    idx = find_line(all_lines, ["DNI", "L.C.", "L.E.", "Nº"], start=idx_seccion)
    if idx is not None:
        dni, cuit = _parse_dni_cuit(all_lines[idx]["text"])
        campos[prefix + "DNI"] = _clean(dni)
        campos[prefix + "CUIT"] = _clean(cuit)

    idx = find_line(all_lines, ["Fecha", "de", "nacimiento", "Sexo"], start=idx_seccion)
    if idx is not None:
        fecha, sexo_m, sexo_f = _parse_fecha_nacimiento_sexo(all_lines[idx])
        campos[prefix + "Fecha de nacimiento"] = fecha
        campos[prefix + "Sexo - Masculino"] = sexo_m
        campos[prefix + "Sexo - Femenino"] = sexo_f

    idx = find_line(all_lines, ["Nacionalidad", "Lugar", "de", "nacimiento"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        nac_end = word_x1(line, "Nacionalidad")
        lugar_x0 = word_x0(line, "Lugar")
        if nac_end is not None and lugar_x0 is not None:
            campos[prefix + "Nacionalidad"] = _clean(value_between(line, nac_end, lugar_x0))
        campos[prefix + "Lugar de nacimiento"] = _titlecase_es(_value_after_label(line, "nacimiento"))

    idx = find_line(all_lines, ["Estado", "civil", "Actividad", "principal"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        civil_end = word_x1(line, "civil")
        actividad_x0 = word_x0(line, "Actividad")
        if civil_end is not None and actividad_x0 is not None:
            campos[prefix + "Estado civil"] = _clean(value_between(line, civil_end, actividad_x0))
        principal_end = word_x1(line, "principal")
        if principal_end is not None:
            campos[prefix + "Actividad principal"] = _titlecase_es(value_between(line, principal_end, 10_000))

    idx = find_line(all_lines, ["Domicilio:", "Calle"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        calle_end = word_x1(line, "Calle")
        if calle_end is not None:
            campos[prefix + "Domicilio completo"] = _titlecase_es(value_between(line, calle_end, 10_000))

    idx = find_line(all_lines, ["Localidad", "Provincia"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        loc_end = word_x1(line, "Localidad")
        prov_x0 = word_x0(line, "Provincia")
        if loc_end is not None and prov_x0 is not None:
            campos[prefix + "Localidad"] = _titlecase_es(value_between(line, loc_end, prov_x0))
        prov_end = word_x1(line, "Provincia")
        if prov_end is not None:
            campos[prefix + "Provincia"] = _clean(value_between(line, prov_end, 10_000))

    idx = find_line(all_lines, ["Código", "Postal", "País"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        postal_end = word_x1(line, "Postal")
        pais_x0 = word_x0(line, "País")
        if postal_end is not None and pais_x0 is not None:
            campos[prefix + "Código Postal"] = _clean(value_between(line, postal_end, pais_x0))
        pais_end = word_x1(line, "País")
        if pais_end is not None:
            campos[prefix + "País"] = _clean(value_between(line, pais_end, 10_000))

    idx = find_line(all_lines, ["Tel.", "particular"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        part_end = word_x1(line, "particular")
        tel_words = [w for w in line["words"] if w["text"] == "Tel."]
        tel2_x0 = tel_words[1]["x0"] if len(tel_words) >= 2 else None
        if part_end is not None and tel2_x0 is not None:
            campos[prefix + "Tel. particular"] = _clean(value_between(line, part_end, tel2_x0))
        cel_end = word_x1(line, "celular")
        if cel_end is not None:
            campos[prefix + "Tel. celular"] = _clean(value_between(line, cel_end, 10_000))

    idx = find_line(all_lines, ["E-mail"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        email_end = word_x1(line, "E-mail")
        if email_end is not None:
            campos[prefix + "E-mail"] = _clean(value_between(line, email_end, 10_000))

    idx = find_line(all_lines, ["Condición", "frente", "al", "I.V.A."], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        anchors = []
        for w in line["words"]:
            if w["text"] == "Final":
                anchors.append(("Consumidor Final", w["x0"]))
            elif w["text"] == "Insc.":
                anchors.append(("Responsable Inscripto", w["x0"]))
            elif w["text"] == "Gravado":
                anchors.append(("No Gravado", w["x0"]))
            elif w["text"] == "Exento":
                anchors.append(("Exento", w["x0"]))
            elif w["text"] == "Monotributista":
                anchors.append(("Monotributista", w["x0"]))
        if anchors:
            marks = nearest_checkbox_label(line, anchors)
            campos[prefix + "IVA - Consumidor Final"] = marks.get("Consumidor Final", "No marcado")

    return campos


# ---------------------------------------------------------------------
# Bloque 4 / 4b. VIDA ASEGURADA 1 (Primera Vida) / VIDA ASEGURADA 2
# (Segunda Vida) -- mismos campos y mismo patrón en las dos, cambia solo
# el prefijo de campo y dónde arranca la sección en el PDF.
# ---------------------------------------------------------------------
def _campos_vida_asegurada_vacios(prefix):
    return {
        prefix + "Nombre y Apellido": None,
        prefix + "DNI": None,
        prefix + "CUIT/CUIL/CDI": None,
        prefix + "Fecha de nacimiento": None,
        prefix + "Sexo - Masculino": None,
        prefix + "Sexo - Femenino": None,
        prefix + "Estado civil": None,
        prefix + "Nacionalidad": None,
        prefix + "Lugar de nacimiento": None,
        prefix + "Domicilio de residencia": None,
        prefix + "Relación con el Solicitante": None,
        prefix + "Profesión": None,
        prefix + "Descripción trabajo/ocupación": None,
        prefix + "Trabajo Manual %": None,
        prefix + "Trabajo No Manual %": None,
        prefix + "Ingresos últimos 12 meses": None,
        prefix + "Actividad peligrosa - Sí": None,
        prefix + "Actividad peligrosa - No": None,
        prefix + "Actividad peligrosa - Detalle": None,
        prefix + "Actividad peligrosa - Frecuencia": None,
        prefix + "¿Fumador últimos 12 meses? - Sí": None,
        prefix + "¿Fumador últimos 12 meses? - No": None,
        prefix + "Tabaco - Producto y cantidad diaria": None,
        prefix + "¿Visitar/residir/trabajar en otro país? - Sí": None,
        prefix + "¿Visitar/residir/trabajar en otro país? - No": None,
        prefix + "Exterior - País": None,
        prefix + "Exterior - Razón": None,
        prefix + "Exterior - Visitas al año": None,
        prefix + "Exterior - Plazo por visita": None,
    }


def _extraer_vida_asegurada(all_lines, idx_seccion, prefix):
    """Lee los campos de una Vida Asegurada (Primera o Segunda) a partir de
    la línea `idx_seccion` donde arranca esa sección.

    Los campos de viaje al exterior (País / Razón / Visitas al año / Plazo
    por visita) NO están validados contra un ejemplo real con "Sí" marcado
    -- en las 5 solicitudes de prueba disponibles todas contestaron "No" a
    esa pregunta. La extracción ahí es best-effort (mismas columnas por
    coordenada que Manual %/No Manual %, pero sin caso real para confirmar
    que las columnas quedan bien asignadas) -- revisar en cuanto aparezca
    una solicitud real con esa pregunta en "Sí"."""
    campos = _campos_vida_asegurada_vacios(prefix)
    for k in (
        "Sexo - Masculino", "Sexo - Femenino",
        "Actividad peligrosa - Sí", "Actividad peligrosa - No",
        "¿Fumador últimos 12 meses? - Sí", "¿Fumador últimos 12 meses? - No",
        "¿Visitar/residir/trabajar en otro país? - Sí", "¿Visitar/residir/trabajar en otro país? - No",
    ):
        campos[prefix + k] = "No marcado"

    # "Nombre y Apellido" también aparece dentro de la nota "...complete su
    # Nombre y Apellido y continue completando desde 'Profesión'" que
    # precede a este campo -- si la Vida Asegurada coincide con un
    # Solicitante, el formulario no repite el nombre y esa nota queda como
    # único match, dando basura. Se descarta cualquier línea con "coincide"
    # (única en esa nota) y, si no queda ninguna otra, el campo es None: no
    # hay nombre tipeado literal para leer (dato derivado, no extraíble).
    idx = None
    for i in range(idx_seccion, len(all_lines)):
        text = all_lines[i]["text"]
        if "Nombre y Apellido" in text and "coincide" not in text:
            idx = i
            break
    if idx is not None:
        line = all_lines[idx]
        apellido_end = word_x1(line, "Apellido")
        if apellido_end is not None:
            campos[prefix + "Nombre y Apellido"] = _clean(value_between(line, apellido_end, 10_000))

    idx = find_line(all_lines, ["DNI", "L.C.", "L.E.", "Nº"], start=idx_seccion)
    if idx is not None:
        dni, cuit = _parse_dni_cuit(all_lines[idx]["text"])
        campos[prefix + "DNI"] = _clean(dni)
        campos[prefix + "CUIT/CUIL/CDI"] = _clean(cuit)

    idx = find_line(all_lines, ["Fecha", "de", "nacimiento", "Sexo"], start=idx_seccion)
    if idx is not None:
        fecha, sexo_m, sexo_f = _parse_fecha_nacimiento_sexo(all_lines[idx])
        campos[prefix + "Fecha de nacimiento"] = fecha
        campos[prefix + "Sexo - Masculino"] = sexo_m
        campos[prefix + "Sexo - Femenino"] = sexo_f

    idx = find_line(all_lines, ["Estado", "civil", "Nacionalidad", "Lugar", "de", "nacimiento"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        civil_end = word_x1(line, "civil")
        nac_x0 = word_x0(line, "Nacionalidad")
        if civil_end is not None and nac_x0 is not None:
            campos[prefix + "Estado civil"] = _clean(value_between(line, civil_end, nac_x0))
        nac_end = word_x1(line, "Nacionalidad")
        lugar_x0 = word_x0(line, "Lugar")
        if nac_end is not None and lugar_x0 is not None:
            campos[prefix + "Nacionalidad"] = _clean(value_between(line, nac_end, lugar_x0))
        campos[prefix + "Lugar de nacimiento"] = _titlecase_es(_value_after_label(line, "nacimiento"))

    idx = find_line(all_lines, ["Domicilio", "de", "residencia"], start=idx_seccion)
    if idx is not None:
        campos[prefix + "Domicilio de residencia"] = _clean(_value_after_label(all_lines[idx], "residencia"))

    idx = find_line(all_lines, ["Relación", "entre", "la", "Vida", "Asegurada"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        pol_end = word_x1(line, "Póliza:")
        if pol_end is not None:
            campos[prefix + "Relación con el Solicitante"] = _clean(value_between(line, pol_end, 10_000))

    # "Profesión" (entre comillas) también aparece en la nota "...continue
    # completando desde 'Profesión'" -- se descarta esa línea igual que se
    # hizo arriba con "Nombre y Apellido"/"coincide".
    idx = None
    for i in range(idx_seccion, len(all_lines)):
        text = all_lines[i]["text"]
        if "Profesión" in text and "completando" not in text:
            idx = i
            break
    if idx is not None:
        campos[prefix + "Profesión"] = _titlecase_es(_value_after_label(all_lines[idx], "Profesión"))

    idx_cap = find_line(all_lines, ["Descripción del trabajo"], start=idx_seccion)
    if idx_cap is not None and idx_cap + 1 < len(all_lines):
        valor = all_lines[idx_cap + 1]["text"].strip()
        m = re.match(r"^(.*?)\s+(\d{1,3})\s+(\d{1,3})$", valor)
        if m:
            campos[prefix + "Descripción trabajo/ocupación"] = _titlecase_es(m.group(1))
            campos[prefix + "Trabajo Manual %"] = m.group(2)
            campos[prefix + "Trabajo No Manual %"] = m.group(3)

    idx = find_line(all_lines, ["ingresos personales"], start=idx_seccion)
    if idx is not None:
        m = re.search(r"([\d][\d.,]*)\s*$", all_lines[idx]["text"])
        if m:
            campos[prefix + "Ingresos últimos 12 meses"] = m.group(1)

    idx = find_line(all_lines, ["esta lista"], start=idx_seccion)
    if idx is not None:
        si, no = _parse_si_no(all_lines[idx])
        campos[prefix + "Actividad peligrosa - Sí"] = si
        campos[prefix + "Actividad peligrosa - No"] = no

    idx_cap = find_line(all_lines, ["Actividad", "Frecuencia"], start=idx_seccion)
    if idx_cap is not None and idx_cap + 1 < len(all_lines):
        cap_line = all_lines[idx_cap]
        val_line = all_lines[idx_cap + 1]
        if val_line["top"] - cap_line["top"] < 30:
            actividad_x0 = word_x0(cap_line, "Actividad")
            frecuencia_x0 = word_x0(cap_line, "Frecuencia")
            if actividad_x0 is not None and frecuencia_x0 is not None:
                # -_COL_TOLERANCE: la fila de valores puede arrancar unos
                # pocos puntos a la izquierda de la etiqueta de columna
                # (visto en un ejemplo real: "Ninguna" empieza 1.1pt antes
                # que "Actividad").
                campos[prefix + "Actividad peligrosa - Detalle"] = _clean(
                    value_between(val_line, actividad_x0 - _COL_TOLERANCE, frecuencia_x0 - _COL_TOLERANCE)
                )
                campos[prefix + "Actividad peligrosa - Frecuencia"] = _clean(
                    value_between(val_line, frecuencia_x0 - _COL_TOLERANCE, 10_000)
                )

    idx = find_line(all_lines, ["fumado"], start=idx_seccion)
    if idx is not None:
        si, no = _parse_si_no(all_lines[idx])
        campos[prefix + "¿Fumador últimos 12 meses? - Sí"] = si
        campos[prefix + "¿Fumador últimos 12 meses? - No"] = no
        m = re.search(r"por\s+d.a\s*(.*)$", all_lines[idx]["text"])
        # el detalle de tabaco puede venir en la misma línea de la pregunta
        # ("...por día 10 CIGARRILLOS POR DIA") o, si no entra, en la línea
        # siguiente -- probamos las dos.
        detalle = _clean(m.group(1)) if m else None
        if not detalle and idx + 1 < len(all_lines):
            sig = all_lines[idx + 1]["text"]
            m2 = re.search(r"por\s+d.a\s*(.*)$", sig)
            if m2:
                detalle = _clean(m2.group(1))
        campos[prefix + "Tabaco - Producto y cantidad diaria"] = detalle

    idx = find_line(all_lines, ["Piensa"], start=idx_seccion)
    if idx is not None:
        si, no = _parse_si_no(all_lines[idx])
        campos[prefix + "¿Visitar/residir/trabajar en otro país? - Sí"] = si
        campos[prefix + "¿Visitar/residir/trabajar en otro país? - No"] = no

    idx_cap = find_line(all_lines, ["visitas al año de cada visita"], start=idx_seccion)
    if idx_cap is not None and idx_cap + 1 < len(all_lines):
        cap_line = all_lines[idx_cap]
        val_line = all_lines[idx_cap + 1]
        if val_line["top"] - cap_line["top"] < 30:
            idx_col1 = find_line(all_lines, ["País", "Razón"], start=idx_seccion, )
            idx_col2 = find_line(all_lines, ["Cuántas", "Plazo"], start=idx_seccion)
            pais_x0 = word_x0(all_lines[idx_col1], "País") if idx_col1 is not None else None
            razon_x0 = word_x0(all_lines[idx_col1], "Razón") if idx_col1 is not None else None
            cuantas_x0 = word_x0(all_lines[idx_col2], "Cuántas") if idx_col2 is not None else None
            plazo_x0 = word_x0(all_lines[idx_col2], "Plazo") if idx_col2 is not None else None
            if pais_x0 is not None and razon_x0 is not None:
                pais_x0 -= _COL_TOLERANCE
                razon_x0 -= _COL_TOLERANCE
                campos[prefix + "Exterior - País"] = _clean(value_between(val_line, pais_x0, razon_x0))
                if cuantas_x0 is not None:
                    cuantas_x0 -= _COL_TOLERANCE
                    campos[prefix + "Exterior - Razón"] = _clean(value_between(val_line, razon_x0, cuantas_x0))
                    if plazo_x0 is not None:
                        plazo_x0 -= _COL_TOLERANCE
                        campos[prefix + "Exterior - Visitas al año"] = _clean(
                            value_between(val_line, cuantas_x0, plazo_x0)
                        )
                        campos[prefix + "Exterior - Plazo por visita"] = _clean(
                            value_between(val_line, plazo_x0, 10_000)
                        )

    return campos


def extract_bloque_4(all_lines):
    """VIDA ASEGURADA 1 (Primera Vida Asegurada). El número de esta sección
    varía según la plantilla ('3. Datos de la Vida Asegurada' en Options 1
    vida vs '4. Datos de la/s Vida/s Asegurada/s' en Options 2 vidas /
    Invest Future), así que se la ubica por el texto SIN el número (regex,
    no find_line a secas)."""
    idx_seccion = None
    for i, line in enumerate(all_lines):
        if re.search(r"Datos de la.*Vida.*Asegurada", line["text"]):
            idx_seccion = i
            break
    prefix = "VIDA ASEGURADA 1 - "
    if idx_seccion is None:
        return _campos_vida_asegurada_vacios(prefix)
    return _extraer_vida_asegurada(all_lines, idx_seccion, prefix)


def extract_bloque_4b(all_lines):
    """VIDA ASEGURADA 2 (Segunda Vida Asegurada). Solo existe en pólizas de
    2 vidas -- si no está el subtítulo "Segunda Vida Asegurada", todos los
    campos quedan en None."""
    idx_seccion = find_line(all_lines, ["Segunda Vida Asegurada"])
    prefix = "VIDA ASEGURADA 2 - "
    if idx_seccion is None:
        return _campos_vida_asegurada_vacios(prefix)
    return _extraer_vida_asegurada(all_lines, idx_seccion, prefix)


# ---------------------------------------------------------------------
# Bloque 5. Seguros existentes
# ---------------------------------------------------------------------
def _grupos_si_no(line, etiqueta_a="Si", etiqueta_b="No"):
    """Una línea puede traer más de un par de opciones en columnas
    separadas (ej. una para Primera Vida y otra para Segunda Vida en la
    misma fila). Empareja cada etiqueta_a con la etiqueta_b más cercana a
    su derecha y busca una 'X' entre ambas para decidir cuál está
    marcada. Sirve tanto para "Si"/"No" como para pares de opciones con
    otro texto (ej. "Pesos"/"Dólares"). Devuelve una lista de
    (x0_del_par, marcado_a, marcado_b) ordenada de izquierda a derecha."""
    sis = sorted((w for w in line["words"] if w["text"] == etiqueta_a), key=lambda w: w["x0"])
    nos = [w for w in line["words"] if w["text"] == etiqueta_b]
    xs = [w for w in line["words"] if w["text"] == "X"]

    grupos = []
    for si in sis:
        candidatos_no = [n for n in nos if n["x0"] > si["x0"]]
        if not candidatos_no:
            continue
        no = min(candidatos_no, key=lambda n: n["x0"])
        marcado_si, marcado_no = "No marcado", "No marcado"
        for x in xs:
            # Margen generoso: en ejemplos reales la 'X' puede aparecer
            # hasta ~11pt antes de 'Si' (ej. "X Si No"), no pegada.
            if si["x0"] - 20 <= x["x0"] <= no["x1"] + 20:
                if (x["x0"] - si["x0"]) < (no["x0"] - x["x0"]):
                    marcado_si = "Marcado"
                else:
                    marcado_no = "Marcado"
        grupos.append((si["x0"], marcado_si, marcado_no))
    return grupos


def extract_bloque_5(all_lines):
    """5. Seguros existentes -- 2 preguntas Sí/No (otra solicitud en los
    últimos 6 meses / rechazo o condición especial) con su detalle en
    tabla, repetidas por Vida Asegurada en las pólizas de 2 vidas (la
    plantilla pone Primera Vida y Segunda Vida en columnas lado a lado en
    el mismo renglón).

    OJO -- en el único ejemplo real de 2 vidas disponible
    (Zurich Options-AECLIF-1354029), la pregunta de "otra solicitud"
    efectivamente trae dos pares Si/No (uno por columna), pero la de
    "rechazo/condición especial" trae UN SOLO par Si/No en todo el PDF,
    aunque el Diccionario_Campos define un campo por Vida Asegurada para
    las dos preguntas. Confirmado contra Base_Combinada que en ese caso la
    misma respuesta se replica en las dos vidas (no es que la respuesta de
    la Vida 1 quede sin dato) -- así que cuando una pregunta trae un solo
    par Si/No en una solicitud de 2 vidas, se lo asigna a ambas. Si
    aparece un segundo ejemplo de 2 vidas que contradiga esto, revisar.

    Las tablas de detalle (Nombre de la compañía, Monto, Fecha, etc.) no
    se extraen: en los 5 ejemplos disponibles las 2 preguntas siempre
    salieron "No", así que no hay ningún caso real con esas tablas
    cargadas para calibrar la extracción."""
    campos = {}
    for n in (1, 2):
        prefix = f"VIDA ASEGURADA {n} - "
        campos[prefix + "Otra solicitud últimos 6 meses - Sí"] = None
        campos[prefix + "Otra solicitud últimos 6 meses - No"] = None
        campos[prefix + "Detalle otras solicitudes"] = None
        campos[prefix + "Rechazo/condición especial - Sí"] = None
        campos[prefix + "Rechazo/condición especial - No"] = None
        campos[prefix + "Detalle rechazo/reclamo"] = None

    idx_seccion = find_line(all_lines, ["Seguros existentes"])
    if idx_seccion is None:
        return campos

    # Umbral de columna: si hay "Segunda Vida" en el encabezado, todo lo
    # que caiga a la derecha de su x0 es de la Vida Asegurada 2.
    idx_header = find_line(all_lines, ["Primera", "Segunda"], start=idx_seccion)
    umbral_col2 = None
    if idx_header is not None:
        segunda_x0 = word_x0(all_lines[idx_header], "Segunda")
        primera_x0 = word_x0(all_lines[idx_header], "Primera")
        if segunda_x0 is not None and primera_x0 is not None:
            umbral_col2 = (primera_x0 + segunda_x0) / 2

    def _asignar(sufijo_si, sufijo_no, idx_linea):
        if idx_linea is None:
            return
        grupos = _grupos_si_no(all_lines[idx_linea])
        if len(grupos) == 1 and umbral_col2 is not None:
            # Es una solicitud de 2 vidas pero esta pregunta puntual solo
            # trae UN par Si/No en todo el ancho de la página (confirmado
            # contra Base_Combinada: en ese caso la misma respuesta aplica
            # a las dos vidas, no es que falte la de una).
            _, si, no = grupos[0]
            for n in (1, 2):
                campos[f"VIDA ASEGURADA {n} - {sufijo_si}"] = si
                campos[f"VIDA ASEGURADA {n} - {sufijo_no}"] = no
            return
        for x0, si, no in grupos:
            n = 2 if (umbral_col2 is not None and x0 >= umbral_col2) else 1
            campos[f"VIDA ASEGURADA {n} - {sufijo_si}"] = si
            campos[f"VIDA ASEGURADA {n} - {sufijo_no}"] = no

    # Las dos preguntas son oraciones largas que a veces envuelven en más
    # de una línea, y el "Si X No" puede terminar en el renglón siguiente
    # al que tiene el inicio de la pregunta (varía según si es de 1 o 2
    # vidas). Más simple y robusto: tomar, en orden, las primeras dos
    # líneas después del encabezado que traen los tokens "Si" y "No"
    # (son, en ese orden, "otra solicitud" y "rechazo/condición especial").
    idxs_si_no = []
    for i in range(idx_seccion, len(all_lines)):
        palabras = {w["text"] for w in all_lines[i]["words"]}
        if "Si" in palabras and "No" in palabras:
            idxs_si_no.append(i)
        if len(idxs_si_no) == 2:
            break

    if len(idxs_si_no) >= 1:
        _asignar("Otra solicitud últimos 6 meses - Sí", "Otra solicitud últimos 6 meses - No", idxs_si_no[0])
    if len(idxs_si_no) >= 2:
        _asignar("Rechazo/condición especial - Sí", "Rechazo/condición especial - No", idxs_si_no[1])

    return campos


# ---------------------------------------------------------------------
# Bloque 6. Beneficios Options (Vida 1) -- SOLO aplica a pólizas Options
# (Invest Future tiene su propia sección de beneficios, distinta -- ver
# "6c. Beneficios Invest Future" en Diccionario_Campos, todavía no
# implementada).
# ---------------------------------------------------------------------
def _valores_por_etiqueta(line, etiqueta):
    """Para una línea con la etiqueta repetida en 2 columnas (ej. 'Monto
    60.000 Monto 60.000'), devuelve una lista de (x0_de_la_etiqueta,
    valor_a_la_derecha) -- valor es None si no hay nada cargado ahí (ej.
    'Monto Monto', sin números, cuando la respuesta fue 'No')."""
    ocurrencias = sorted((w for w in line["words"] if w["text"] == etiqueta), key=lambda w: w["x0"])
    palabras = sorted(line["words"], key=lambda w: w["x0"])
    resultado = []
    for w in ocurrencias:
        siguientes = [p for p in palabras if p["x0"] > w["x0"] and p["text"] != etiqueta]
        valor = None
        if siguientes:
            candidata = siguientes[0]
            otras_despues = [o for o in ocurrencias if o["x0"] > w["x0"]]
            if not otras_despues or candidata["x0"] < otras_despues[0]["x0"]:
                valor = candidata["text"]
        resultado.append((w["x0"], valor))
    return resultado


def _beneficio_si_no_monto(all_lines, idx_caption, umbral_col2, con_monto=True, ventana=4):
    """Lee un beneficio Sí/No (+ Monto opcional) a partir de la línea de
    su etiqueta. El Sí/No a veces está en la misma línea que la etiqueta y
    a veces en una cercana (incluso una línea antes: visto en un ejemplo
    real con "Beneficio por Pérdida de Miembros", donde el renglón de
    checkboxes se imprime arriba de su propia etiqueta) -- se busca por
    distancia mínima a la etiqueta (primero la misma línea, después ±1,
    ±2...) en vez de un rango ciego, para no "contaminarse" agarrando la
    fila de Monto de OTRO beneficio vecino que también caiga dentro de un
    rango ancho.

    El Monto, en cambio, siempre viene después del Sí/No (nunca antes) --
    se busca solo hacia adelante desde ahí.

    Devuelve un dict {1: {"si":..,"no":..,"monto":..}, 2: {...}}."""
    resultado = {1: {"si": "No marcado", "no": "No marcado", "monto": None},
                 2: {"si": "No marcado", "no": "No marcado", "monto": None}}
    if idx_caption is None:
        return resultado

    idx_checkbox = None
    for dist in range(0, ventana + 1):
        candidatos = {idx_caption + dist, idx_caption - dist} if dist else {idx_caption}
        for i in sorted(c for c in candidatos if 0 <= c < len(all_lines)):
            if len(_grupos_si_no(all_lines[i])) >= 1:
                idx_checkbox = i
                break
        if idx_checkbox is not None:
            break

    if idx_checkbox is not None:
        for x0, si, no in _grupos_si_no(all_lines[idx_checkbox]):
            n = 2 if (umbral_col2 is not None and x0 >= umbral_col2) else 1
            resultado[n]["si"] = si
            resultado[n]["no"] = no

    if con_monto:
        # Empieza EN la línea del checkbox (no en la siguiente): en algunas
        # solicitudes de 1 vida, "Beneficio por X ... Si No Monto <valor>"
        # viene todo en un solo renglón; en la de 2 vidas usada como
        # referencia, en cambio, el Monto cae en una fila aparte más abajo.
        punto_partida = idx_checkbox if idx_checkbox is not None else idx_caption
        idx_monto = None
        for i in range(punto_partida, min(len(all_lines), punto_partida + ventana)):
            if len(_valores_por_etiqueta(all_lines[i], "Monto")) >= 1:
                idx_monto = i
                break
        if idx_monto is not None:
            for x0, valor in _valores_por_etiqueta(all_lines[idx_monto], "Monto"):
                n = 2 if (umbral_col2 is not None and x0 >= umbral_col2) else 1
                resultado[n]["monto"] = valor

    return resultado


def extract_bloque_6(all_lines):
    """6. Beneficios Options (Vida 1) y 6b (Vida 2) -- tabla de beneficios
    adicionales, en columnas Primera/Segunda Vida Asegurada igual que el
    Bloque 5. Solo existe en pólizas Options; en Invest Future (que tiene
    su propia sección "6c", no implementada) queda todo en None.

    "Beneficio de Renta Familiar" no usa "Monto" sino "Renta anual" /
    "Años" -- se extrae aparte y NO está validado contra un ejemplo real
    con "Sí" marcado (en la única solicitud de prueba con este bloque
    contestó "No")."""
    campos = {}
    for n in (1, 2):
        prefix = "VIDA ASEGURADA 1 - " if n == 1 else "VIDA ASEGURADA 2 - "
        campos[prefix + "Seguro de Vida Adicional - Sí"] = None
        campos[prefix + "Seguro de Vida Adicional - No"] = None
        campos[prefix + "Seguro de Vida Adicional - Monto"] = None
        campos[prefix + "Enfermedad Grave - Sí"] = None
        campos[prefix + "Enfermedad Grave - No"] = None
        campos[prefix + "Enfermedad Grave - Monto"] = None
        campos[prefix + "Renta Familiar - Sí"] = None
        campos[prefix + "Renta Familiar - No"] = None
        campos[prefix + "Renta Familiar - Monto anual"] = None
        campos[prefix + "Renta Familiar - Años"] = None
        campos[prefix + "Muerte Accidental - Sí"] = None
        campos[prefix + "Muerte Accidental - No"] = None
        campos[prefix + "Muerte Accidental - Monto"] = None
        campos[prefix + "Hospitalización - Sí"] = None
        campos[prefix + "Hospitalización - No"] = None
        campos[prefix + "Hospitalización - Monto"] = None
        campos[prefix + "Invalidez Total y Permanente - Sí"] = None
        campos[prefix + "Invalidez Total y Permanente - No"] = None
        campos[prefix + "Invalidez Total y Permanente - Monto"] = None
        campos[prefix + "Pérdida de Miembros - Sí"] = None
        campos[prefix + "Pérdida de Miembros - No"] = None
        campos[prefix + "Pérdida de Miembros - Monto"] = None
        campos[prefix + "Exención de Pago de Primas - Sí"] = None
        campos[prefix + "Exención de Pago de Primas - No"] = None

    # Regex en vez de find_line con el texto completo: en 2 de los 3 PDF
    # Options de prueba, "Seguro" sale corrompido en este título puntual
    # ("Beneficios Adicionales al Seg o de Vida..." -- falta "ur", parece
    # un glitch de renderizado del PDF, no algo sistemático en todo el
    # documento). ".*?" tolera lo que sea que haya quedado en el medio.
    idx_seccion = None
    for i, line in enumerate(all_lines):
        if re.search(r"Beneficios Adicionales al Se.*?de Vida", line["text"]):
            idx_seccion = i
            break
    if idx_seccion is None:
        return campos

    idx_header = find_line(all_lines, ["Primera", "Vida", "Asegurada", "Segunda"], start=idx_seccion)
    umbral_col2 = None
    if idx_header is not None:
        primera_x0 = word_x0(all_lines[idx_header], "Primera")
        segunda_x0 = word_x0(all_lines[idx_header], "Segunda")
        if primera_x0 is not None and segunda_x0 is not None:
            umbral_col2 = (primera_x0 + segunda_x0) / 2

    def _volcar(nombre_campo, idx_caption, con_monto=True):
        r = _beneficio_si_no_monto(all_lines, idx_caption, umbral_col2, con_monto=con_monto)
        # Si no hay columna de Segunda Vida en esta solicitud (1 vida),
        # _beneficio_si_no_monto igual devuelve un default "No marcado"
        # para n=2 -- no corresponde escribirlo, esa columna no existe.
        vidas = (1, 2) if umbral_col2 is not None else (1,)
        for n in vidas:
            prefix = "VIDA ASEGURADA 1 - " if n == 1 else "VIDA ASEGURADA 2 - "
            campos[prefix + f"{nombre_campo} - Sí"] = r[n]["si"]
            campos[prefix + f"{nombre_campo} - No"] = r[n]["no"]
            if con_monto:
                campos[prefix + f"{nombre_campo} - Monto"] = r[n]["monto"]

    # Monto del Seguro de Vida Adicional: no tiene Sí/No, siempre se carga.
    # Ojo: la propia línea del título empieza con la palabra "Monto"
    # ("Monto del Seguro de Vida Adicional deseado"), y en algunas
    # solicitudes (1 vida) el valor real viene pegado en ESA MISMA línea
    # ("...deseado Monto 100.000"), mientras que en otras (2 vidas) viene
    # 2 líneas más abajo, en una fila aparte. Por eso se busca desde idx
    # (no idx+1) pero se descarta cualquier "valor" que no sea numérico
    # (como "del", que es la palabra siguiente al "Monto" del título).
    idx = find_line(all_lines, ["Monto del Seguro de Vida Adicional"], start=idx_seccion)
    if idx is not None:
        for i in range(idx, min(len(all_lines), idx + 4)):
            valores = [
                (x0, v) for x0, v in _valores_por_etiqueta(all_lines[i], "Monto")
                if v is not None and re.fullmatch(r"[\d.,]+", v)
            ]
            if valores:
                for x0, valor in valores:
                    n = 2 if (umbral_col2 is not None and x0 >= umbral_col2) else 1
                    prefix = "VIDA ASEGURADA 1 - " if n == 1 else "VIDA ASEGURADA 2 - "
                    campos[prefix + "Seguro de Vida Adicional - Monto"] = valor
                break

    idx = find_line(all_lines, ["Beneficio por Enfermedad Grave"], start=idx_seccion)
    _volcar("Enfermedad Grave", idx)

    # Renta Familiar: el Sí/No sale igual que los demás beneficios, pero
    # "Monto anual" y "Años" NO se intentan extraer -- en los 5 ejemplos
    # disponibles esta pregunta siempre salió "No", así que no hay ninguna
    # fila real con esos valores cargados para calibrar la posición (y la
    # línea de encabezado "Renta anual / Renta anual" por columna es
    # indistinguible de una fila de valores sin un ejemplo real que la
    # contraste). Quedan en None hasta que aparezca un caso con "Sí".
    idx = find_line(all_lines, ["Beneficio de Renta Familiar"], start=idx_seccion)
    r = _beneficio_si_no_monto(all_lines, idx, umbral_col2, con_monto=False)
    for n in ((1, 2) if umbral_col2 is not None else (1,)):
        prefix = "VIDA ASEGURADA 1 - " if n == 1 else "VIDA ASEGURADA 2 - "
        campos[prefix + "Renta Familiar - Sí"] = r[n]["si"]
        campos[prefix + "Renta Familiar - No"] = r[n]["no"]

    idx = find_line(all_lines, ["Beneficio por Muerte Accidental"], start=idx_seccion)
    _volcar("Muerte Accidental", idx)

    idx = find_line(all_lines, ["Beneficio por Hospitalización"], start=idx_seccion)
    _volcar("Hospitalización", idx)

    idx = find_line(all_lines, ["Beneficio por Invalidez Total y Permanente"], start=idx_seccion)
    _volcar("Invalidez Total y Permanente", idx)

    idx = find_line(all_lines, ["Beneficio por Pérdida de Miembros"], start=idx_seccion)
    _volcar("Pérdida de Miembros", idx)

    idx = find_line(all_lines, ["Beneficio de Exención de Pago de Primas"], start=idx_seccion)
    _volcar("Exención de Pago de Primas", idx, con_monto=False)

    return campos


# ---------------------------------------------------------------------
# Bloque 7. Moneda / Inversión
# ---------------------------------------------------------------------
# "Fondo Zurich <nombre>" -> sufijo del campo en Diccionario_Campos. El
# PDF ofrece más fondos de los que el Diccionario trackea (ej. "Zurich
# Competitive" y "Zurich Income D-Link" no tienen campo asignado) -- esos
# se leen igual (para no perderlos silenciosamente del parseo de la
# línea) pero no se vuelcan a ningún campo de salida.
_MAPA_FONDOS = {
    "Money": "Asignación Zurich Money %",
    "Income": "Asignación Zurich Income / Income II %",
    "Income II": "Asignación Zurich Income / Income II %",
    "Performance": "Asignación Zurich Performance %",
    "Commodities": "Asignación Zurich Commodities %",
    "Performance International II": "Asignación Zurich Performance International II % (dólar)",
    "Performance Tech": "Asignación Zurich Performance Tech % (dólar)",
}


def _leer_fondos(line):
    """Busca patrones 'Fondo Zurich <nombre...> <porcentaje o "%" vacío>'
    en una línea -- puede haber más de uno (columnas Pesos/Dólar lado a
    lado). Devuelve una lista de (nombre_fondo, valor_o_None)."""
    words = sorted(line["words"], key=lambda w: w["x0"])
    fondos = []
    i, n = 0, len(words)
    while i < n:
        if words[i]["text"] == "Fondo" and i + 1 < n and words[i + 1]["text"] == "Zurich":
            nombre_partes = []
            j = i + 2
            valor = None
            while j < n:
                texto = words[j]["text"]
                if texto == "%":
                    j += 1
                    break
                if texto.endswith("%"):
                    valor = texto[:-1]
                    j += 1
                    break
                nombre_partes.append(texto)
                j += 1
            fondos.append((" ".join(nombre_partes), valor))
            i = j
        else:
            i += 1
    return fondos


def extract_bloque_7(all_lines):
    """7. Moneda / Inversión. "Cuenta Individual - Pesos/Dólares" es común
    a Options e Invest Future; el resto de los campos ("Pago en adición a
    Cuenta Individual", "Estrategia Predeterminada", "Asignación Zurich
    X %") son EXCLUSIVOS de Invest Future -- confirmado contra
    Base_Combinada (vienen "N/A" en las 3 solicitudes Options de prueba).
    Quedan en None si no se encuentra la pregunta correspondiente, que es
    lo que pasa en Options.

    La tabla de fondos ("Asignación Zurich X %") solo se completa cuando
    "Estrategia Predeterminada" es "No" -- si es "Sí" no hay tabla manual
    que leer, y el único ejemplo real disponible (Invest Future Joven)
    tiene justamente "No", así que la extracción de la tabla sí está
    validada contra un caso real (75%/25% en dos fondos dólar)."""
    campos = {
        "Cuenta Individual - Pesos": None,
        "Cuenta Individual - Dólares": None,
        "Pago en adición a Cuenta Individual - Sí": None,
        "Pago en adición a Cuenta Individual - No": None,
        "Estrategia Predeterminada - Sí": None,
        "Estrategia Predeterminada - No": None,
        "Asignación Zurich Money %": None,
        "Asignación Zurich Income / Income II %": None,
        "Asignación Zurich Performance %": None,
        "Asignación Zurich Commodities %": None,
        "Asignación Zurich Performance International II % (dólar)": None,
        "Asignación Zurich Performance Tech % (dólar)": None,
    }

    idx = None
    for i, line in enumerate(all_lines):
        if "pague en adición a la cuenta Individual" in line["text"]:
            idx = i
            break
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx])
        if grupos:
            _, si, no = grupos[0]
            campos["Pago en adición a Cuenta Individual - Sí"] = si
            campos["Pago en adición a Cuenta Individual - No"] = no

    idx_seccion = find_line(all_lines, ["Moneda de la Cuenta Individual"])
    if idx_seccion is None:
        return campos

    idx = find_line(all_lines, ["moneda", "seleccionada"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx], "Pesos", "Dólares")
        if grupos:
            _, pesos, dolares = grupos[0]
            campos["Cuenta Individual - Pesos"] = pesos
            campos["Cuenta Individual - Dólares"] = dolares
    else:
        # Plantilla Options: no hay un checkbox "Pesos X Dólares" en una
        # sola línea -- "Pesos" y "Dólares" encabezan cada uno su propia
        # tabla de estrategia más abajo, y la moneda elegida es la que
        # tiene una "X" pegada adelante (ej. "X Dólares Estrategia N° 1
        # ..."). Solo validado contra un ejemplo real con Dólares elegido
        # -- el caso "X Pesos ..." es simétrico pero no está probado.
        for i in range(idx_seccion, min(len(all_lines), idx_seccion + 10)):
            text = all_lines[i]["text"]
            if text.startswith("Pesos") or text.startswith("X Pesos"):
                campos["Cuenta Individual - Pesos"] = "Marcado" if text.startswith("X ") else "No marcado"
            if text.startswith("Dólares") or text.startswith("X Dólares"):
                campos["Cuenta Individual - Dólares"] = "Marcado" if text.startswith("X ") else "No marcado"

    idx = find_line(all_lines, ["Estrategia de Inversión Predeterminada", "disponible"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx])
        if grupos:
            _, si, no = grupos[0]
            campos["Estrategia Predeterminada - Sí"] = si
            campos["Estrategia Predeterminada - No"] = no

    idx_tabla = find_line(all_lines, ["indique los porcentajes de asignación"], start=idx_seccion)
    if idx_tabla is not None:
        for i in range(idx_tabla, min(len(all_lines), idx_tabla + 12)):
            for nombre, valor in _leer_fondos(all_lines[i]):
                campo = _MAPA_FONDOS.get(nombre)
                if campo is not None and valor is not None:
                    campos[campo] = valor

    return campos


# ---------------------------------------------------------------------
# Bloque 8. Prima
# ---------------------------------------------------------------------
def extract_bloque_8(all_lines):
    """8. Prima -- montos (Primas regulares/Prima única/Sellado/Pago
    inicial) y Frecuencia de pago (3 opciones) son comunes a Options e
    Invest Future. El resto se divide igual que en los Bloques 6/7:
    "Póliza Vanishing" y "Actualización de Primas y Beneficios" son
    exclusivos de Options; "Incremento anual automático" (con su nivel
    5%/10% y plazo) es exclusivo de Invest Future -- confirmado contra
    Base_Combinada. "Plazo de pago de primas (años)" resultó ser el MISMO
    valor que "Incremento anual - Plazo (años)" en los 2 ejemplos Invest
    Future disponibles (no una etiqueta propia en el PDF), así que se
    copia de ahí."""
    campos = {
        "Primas regulares (A) VRU$S": None,
        "Prima única (B) VRU$S": None,
        "Sellado sobre Beneficios (C)": None,
        "Pago inicial total": None,
        "Plazo de pago de primas (años)": None,
        "¿Póliza Vanishing? - Sí": None,
        "¿Póliza Vanishing? - No": None,
        "Póliza Vanishing - Años": None,
        "¿Actualización de Primas y Beneficios? - Sí": None,
        "¿Actualización de Primas y Beneficios? - No": None,
        "Frecuencia de pago - Mensual": None,
        "Frecuencia de pago - Semestral": None,
        "Frecuencia de pago - Anual": None,
        "Incremento anual automático - Sí": None,
        "Incremento anual automático - No": None,
        "Incremento anual - 5%": None,
        "Incremento anual - 10%": None,
        "Incremento anual - Plazo (años)": None,
        "Origen de los fondos": None,
    }

    idx_seccion = find_line(all_lines, ["Detalles de la Prima"])
    if idx_seccion is None:
        return campos

    idx = find_line(all_lines, ["Primas regulares", "Prima regular total"], start=idx_seccion)
    if idx is not None:
        m = re.search(r"([\d][\d.,]*)\s*$", all_lines[idx]["text"])
        if m:
            campos["Primas regulares (A) VRU$S"] = m.group(1)

    idx = find_line(all_lines, ["Prima única", "Prima única total"], start=idx_seccion)
    if idx is not None:
        m = re.search(r"([\d][\d.,]*)\s*$", all_lines[idx]["text"])
        if m:
            campos["Prima única (B) VRU$S"] = m.group(1)

    # Fragmento largo a propósito: "Sellado sobre Beneficios" sola también
    # aparece dentro de las explicaciones entre paréntesis de "Primas
    # regulares" y "Prima única" (líneas anteriores a esta), y con un
    # fragmento corto find_line agarraba el monto de esas por error.
    idx = find_line(all_lines, ["Sellado sobre Beneficios (si es aplicable)"], start=idx_seccion)
    if idx is not None:
        m = re.search(r"([\d][\d.,]*)\s*$", all_lines[idx]["text"])
        if m:
            campos["Sellado sobre Beneficios (C)"] = m.group(1)

    idx = find_line(all_lines, ["Pago inicial total"], start=idx_seccion)
    if idx is not None:
        m = re.search(r"([\d][\d.,]*)\s*$", all_lines[idx]["text"])
        if m:
            campos["Pago inicial total"] = m.group(1)

    idx = find_line(all_lines, ["Póliza Vanishing"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        grupos = _grupos_si_no(line)
        if grupos:
            _, si, no = grupos[0]
            campos["¿Póliza Vanishing? - Sí"] = si
            campos["¿Póliza Vanishing? - No"] = no
        campos["Póliza Vanishing - Años"] = _clean(_value_after_label(line, "Años"))

    idx = find_line(all_lines, ["actualización de Primas y Beneficios"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx])
        if grupos:
            _, si, no = grupos[0]
            campos["¿Actualización de Primas y Beneficios? - Sí"] = si
            campos["¿Actualización de Primas y Beneficios? - No"] = no

    idx = find_line(all_lines, ["Frecuencia de pago de las primas regulares"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        anchors = []
        for etq in ("Mensual", "Semestral", "Anual"):
            x0 = word_x0(line, etq)
            if x0 is not None:
                anchors.append((etq, x0))
        if anchors:
            marks = nearest_checkbox_label(line, anchors)
            for etq in ("Mensual", "Semestral", "Anual"):
                campos[f"Frecuencia de pago - {etq}"] = marks.get(etq, "No marcado")

    idx = find_line(all_lines, ["Desea el incremento anual"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx])
        if grupos:
            _, si, no = grupos[0]
            campos["Incremento anual automático - Sí"] = si
            campos["Incremento anual automático - No"] = no

    idx = find_line(all_lines, ["nivel de incremento anual deseado"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx], "5%", "10%")
        if grupos:
            _, cinco, diez = grupos[0]
            campos["Incremento anual - 5%"] = cinco
            campos["Incremento anual - 10%"] = diez

    idx = find_line(all_lines, ["indique el plazo correspondiente"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        fin_label = word_x1(line, "correspondiente")
        inicio_anios = word_x0(line, "Años")
        if fin_label is not None and inicio_anios is not None:
            digitos = "".join(
                w["text"] for w in line["words"]
                if fin_label <= w["x0"] < inicio_anios and w["text"].isdigit()
            )
            if digitos:
                campos["Incremento anual - Plazo (años)"] = digitos
                campos["Plazo de pago de primas (años)"] = digitos

    idx = find_line(all_lines, ["origen en la siguiente actividad"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        fin = word_x1(line, "actividad")
        if fin is not None:
            campos["Origen de los fondos"] = _clean(value_between(line, fin, 10_000))

    return campos


# ---------------------------------------------------------------------
# Bloque 9. Débito
# ---------------------------------------------------------------------
def extract_bloque_9(all_lines):
    """9. Débito. "Medio de pago - Tarjeta de crédito / CBU" no son
    checkboxes explícitos en el PDF -- se derivan de cuál de los dos
    campos (últimos 4 dígitos de Tarjeta o de CBU) vino con datos, ya
    que en la plantilla ambos medios aparecen siempre listados pero solo
    uno se completa. Solo validado con un ejemplo real que usa CBU (los 5
    PDF de prueba pagan por CBU, ninguno por tarjeta)."""
    campos = {
        "Titular medio de pago = Solicitante - Sí": None,
        "Titular medio de pago = Solicitante - No": None,
        "Medio de pago - Tarjeta de crédito": "No marcado",
        "Tarjeta - Últimos 4 dígitos": None,
        "Medio de pago - CBU": "No marcado",
        "CBU - Últimos 4 dígitos": None,
    }

    idx_seccion = None
    for i, line in enumerate(all_lines):
        if re.search(r"Autorización para d.bito", line["text"]):
            idx_seccion = i
            break
    if idx_seccion is None:
        return campos

    idx = find_line(all_lines, ["titular de la cuenta bancaria o tarjeta de crédito utilizada"], start=idx_seccion)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx])
        if grupos:
            _, si, no = grupos[0]
            campos["Titular medio de pago = Solicitante - Sí"] = si
            campos["Titular medio de pago = Solicitante - No"] = no

    idx = find_line(all_lines, ["Nº", "de", "Tarjeta"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        fin = word_x1(line, "Tarjeta")
        if fin is not None:
            digitos = "".join(
                w["text"] for w in line["words"] if w["x0"] >= fin and w["text"].isdigit()
            )
            if digitos:
                campos["Tarjeta - Últimos 4 dígitos"] = digitos[-4:]

    idx = find_line(all_lines, ["C.B.U.", "Nº"], start=idx_seccion)
    if idx is not None:
        line = all_lines[idx]
        digitos = "".join(w["text"] for w in line["words"] if w["text"].isdigit())
        if digitos:
            campos["CBU - Últimos 4 dígitos"] = digitos[-4:]

    if campos["Tarjeta - Últimos 4 dígitos"]:
        campos["Medio de pago - Tarjeta de crédito"] = "Marcado"
    if campos["CBU - Últimos 4 dígitos"]:
        campos["Medio de pago - CBU"] = "Marcado"

    return campos


# ---------------------------------------------------------------------
# Bloque 10. BENEFICIARIOS PRINCIPALES
# ---------------------------------------------------------------------
# Tolerancia horizontal para esta tabla en particular: el nombre tipeado
# empieza unos ~11-20pt a la izquierda de donde arranca la palabra
# "Apellido" del encabezado (visto en varios ejemplos reales) -- más
# ancha que _COL_TOLERANCE porque acá el desfasaje es mayor.
_TOL_TABLA_BENEFICIARIOS = 20


def _sub_bloques_por_vida(all_lines, ini, fin):
    """Una tabla de beneficiarios puede venir partida en dos sub-tablas
    "Primera Vida Asegurada" / "Segunda Vida Asegurada" (pólizas de 2
    vidas) o ser una sola tabla sin ese subtítulo (1 vida). Devuelve una
    lista de (nombre_de_la_vida_o_None, inicio, fin)."""
    idx_primera = None
    for i in range(ini, fin):
        if all_lines[i]["text"].strip() == "Primera Vida Asegurada":
            idx_primera = i
            break
    if idx_primera is None:
        return [(None, ini, fin)]

    idx_segunda = None
    for i in range(idx_primera + 1, fin):
        if all_lines[i]["text"].strip() == "Segunda Vida Asegurada":
            idx_segunda = i
            break
    sub_bloques = [("Primera Vida Asegurada", idx_primera, idx_segunda or fin)]
    if idx_segunda is not None:
        sub_bloques.append(("Segunda Vida Asegurada", idx_segunda, fin))
    return sub_bloques


def extract_bloque_10(all_lines):
    """10. BENEFICIARIOS PRINCIPALES -- hasta 3 beneficiarios, en una
    tabla por columnas (Apellido y nombre / Fecha de nacimiento /
    C.U.I.L.-C.U.I.T / Relación con la Vida Asegurada / %). En pólizas de
    2 vidas la tabla viene partida en dos sub-tablas "Primera/Segunda
    Vida Asegurada" (cada una con sus propios beneficiarios); en pólizas
    de 1 vida es una sola tabla sin ese subtítulo. "Vida asociada" es la
    única excepción a "extraer literal" de este bloque: Base_Combinada la
    guarda como "Vida 1"/"Vida 2" (no la frase completa del PDF), y en
    pólizas de 1 vida la completa como "Vida 1" aunque el PDF no tenga
    ningún subtítulo "Primera Vida Asegurada" que copiar -- se normaliza
    acá porque el mapeo es 100% determinístico (confirmado contra los 5
    ejemplos), no una inferencia de negocio."""
    campos = {}
    for n in (1, 2, 3):
        p = f"BENEFICIARIO PRINCIPAL {n} - "
        campos[p + "Nombre"] = None
        campos[p + "Fecha nacimiento"] = None
        campos[p + "CUIL/CUIT"] = None
        campos[p + "Relación"] = None
        campos[p + "%"] = None
        campos[p + "Vida asociada"] = None

    idx_seccion = None
    for i, line in enumerate(all_lines):
        if re.search(r"Beneficiarios \(en caso de fallecimiento", line["text"]):
            idx_seccion = i
            break
    if idx_seccion is None:
        return campos

    idx_fin = None
    for i in range(idx_seccion, len(all_lines)):
        if "Beneficiarios Contingentes" in all_lines[i]["text"]:
            idx_fin = i
            break
    if idx_fin is None:
        idx_fin = min(len(all_lines), idx_seccion + 30)

    beneficiarios = []
    for vida_asociada, ini, fin in _sub_bloques_por_vida(all_lines, idx_seccion, idx_fin):
        idx_header = None
        for i in range(ini, fin):
            if "Apellido" in all_lines[i]["text"] and "Relación" in all_lines[i]["text"]:
                idx_header = i
                break
        if idx_header is None:
            continue
        header = all_lines[idx_header]
        fecha_x0 = word_x0(header, "Fecha")
        cuil_x0 = word_x0(header, "C.U.I.L./C.U.I.T")
        relacion_x0 = word_x0(header, "Relación")
        pct_x0 = word_x0(header, "%")
        if None in (fecha_x0, cuil_x0, relacion_x0, pct_x0):
            continue

        for i in range(idx_header + 1, fin):
            line = all_lines[i]
            if not line["words"]:
                continue
            nombre = value_between(line, 0, fecha_x0 - _TOL_TABLA_BENEFICIARIOS)
            if not _clean(nombre):
                continue  # línea sin nombre en la primera columna: no es una fila de beneficiario
            fecha = value_between(line, fecha_x0 - _TOL_TABLA_BENEFICIARIOS, cuil_x0 - _TOL_TABLA_BENEFICIARIOS)
            cuil = value_between(line, cuil_x0 - _TOL_TABLA_BENEFICIARIOS, relacion_x0 - _TOL_TABLA_BENEFICIARIOS)
            relacion = value_between(line, relacion_x0 - _TOL_TABLA_BENEFICIARIOS, pct_x0 - _TOL_TABLA_BENEFICIARIOS)
            pct = value_between(line, pct_x0 - _TOL_TABLA_BENEFICIARIOS, 10_000)
            beneficiarios.append({
                "nombre": _titlecase_es(nombre),
                "fecha": _clean(fecha),
                "cuil": _clean(cuil),
                "relacion": _titlecase_es(relacion),
                "pct": _clean(pct),
                # Base_Combinada usa la forma corta "Vida 1"/"Vida 2", no la
                # frase literal del PDF -- y en pólizas de 1 vida (sin
                # subtítulo "Primera/Segunda Vida Asegurada") lo completa
                # igual como "Vida 1" aunque no haya ese texto en el PDF.
                "vida": "Vida 2" if vida_asociada == "Segunda Vida Asegurada" else "Vida 1",
            })

    for n, b in zip((1, 2, 3), beneficiarios):
        p = f"BENEFICIARIO PRINCIPAL {n} - "
        campos[p + "Nombre"] = b["nombre"]
        campos[p + "Fecha nacimiento"] = b["fecha"]
        campos[p + "CUIL/CUIT"] = b["cuil"]
        campos[p + "Relación"] = b["relacion"]
        campos[p + "%"] = b["pct"]
        campos[p + "Vida asociada"] = b["vida"]

    return campos


# ---------------------------------------------------------------------
# Bloque 11. BENEFICIARIOS CONTINGENTES
# ---------------------------------------------------------------------
def extract_bloque_11(all_lines):
    """11. BENEFICIARIOS CONTINGENTES -- Opción A/B (a quién se le paga si
    fallecen los beneficiarios principales) + hasta 2 beneficiarios, en
    una tabla con las mismas columnas que el Bloque 10 más una columna
    extra ("Beneficiario designado asociado", solo aplica con Opción B).

    En los 5 PDF de prueba, Opción A está siempre marcada y solo UNA
    solicitud (Options 2 vidas) tiene beneficiarios contingentes
    realmente cargados -- las otras 4 dejan la tabla vacía. Por eso:
      - "Beneficiario designado asociado (si Opción B)" NO se extrae: no
        hay ningún ejemplo real con Opción B para calibrar esa columna.
      - El nombre puede venir cortado en 2 renglones (visto en el único
        ejemplo real con datos: "RODRIGUEZ LAUANDOS MARIA" + "MERCEDES"
        en la línea siguiente) -- se detecta y concatena de forma
        heurística: si la línea de después de una fila de beneficiario no
        tiene ningún dígito y no es un límite de sección conocido, se
        asume que es la continuación del nombre."""
    campos = {
        "Opción A - declarada": "No marcado",
        "Opción B - declarada": "No marcado",
    }
    for n in (1, 2):
        p = f"BENEFICIARIO CONTINGENTE {n} - "
        campos[p + "Nombre"] = None
        campos[p + "Fecha nacimiento"] = None
        campos[p + "CUIL/CUIT"] = None
        campos[p + "%"] = None
        campos[p + "Beneficiario designado asociado (si Opción B)"] = None
        campos[p + "Vida asociada"] = None

    idx_seccion = None
    for i, line in enumerate(all_lines):
        if re.search(r"\d+\.\s*Beneficiarios Contingentes", line["text"]):
            idx_seccion = i
            break
    if idx_seccion is None:
        return campos

    idx_fin = min(len(all_lines), idx_seccion + 40)
    for i in range(idx_seccion, idx_fin):
        # Dos variantes vistas: "Declaraciones del solicitante..." (2 vidas)
        # y "Autorización para débito" (1 vida, el orden de bloques difiere).
        if re.search(r"\d+\.\s*Declaraciones", all_lines[i]["text"]) or re.search(
            r"Autorización para d.bito", all_lines[i]["text"]
        ):
            idx_fin = i
            break

    idx_a = find_line(all_lines, ["Beneficiarios Contingentes serán considerados"], start=idx_seccion)
    if idx_a is not None and all_lines[idx_a]["text"].strip().startswith("X "):
        campos["Opción A - declarada"] = "Marcado"

    idx_b = None
    for i in range(idx_seccion, idx_fin):
        if all_lines[i]["text"].strip().startswith(("B.", "X B.")):
            idx_b = i
            break
    if idx_b is not None and all_lines[idx_b]["text"].strip().startswith("X "):
        campos["Opción B - declarada"] = "Marcado"

    contingentes = []
    for vida_asociada, ini, fin in _sub_bloques_por_vida(all_lines, idx_seccion, idx_fin):
        idx_header = None
        for i in range(ini, fin):
            if "Fecha" in all_lines[i]["text"] and "nacimiento" in all_lines[i]["text"] and "C.U.I.L" in all_lines[i]["text"]:
                idx_header = i
                break
        idx_header_apellido = None
        for i in range(ini, fin):
            if all_lines[i]["words"] and sum(1 for w in all_lines[i]["words"] if w["text"] == "Apellido") >= 2:
                idx_header_apellido = i
                break
        if idx_header is None or idx_header_apellido is None:
            continue
        fecha_x0 = word_x0(all_lines[idx_header], "Fecha")
        cuil_x0 = word_x0(all_lines[idx_header], "C.U.I.L./C.U.I.T")
        pct_word = next((w for w in all_lines[idx_header]["words"] if w["text"].startswith("%")), None)
        pct_x0 = pct_word["x0"] if pct_word is not None else None
        apellidos_x0 = sorted(w["x0"] for w in all_lines[idx_header_apellido]["words"] if w["text"] == "Apellido")
        col_e_x0 = apellidos_x0[1] if len(apellidos_x0) >= 2 else 10_000
        if None in (fecha_x0, cuil_x0, pct_x0):
            continue

        # La tabla puede empezar más abajo que cualquiera de las 3 líneas
        # de encabezado (vienen desordenadas: "...Solicitud (2)" a veces
        # queda por debajo de las otras dos) -- arrancamos después de la
        # última línea de encabezado que aparezca.
        idx_inicio_filas = max(idx_header, idx_header_apellido) + 1
        for i in range(idx_seccion, fin):
            if "designado en esta Solicitud" in all_lines[i]["text"]:
                idx_inicio_filas = max(idx_inicio_filas, i + 1)

        i = idx_inicio_filas
        while i < fin:
            line = all_lines[i]
            if not line["words"]:
                i += 1
                continue
            nombre = _clean(value_between(line, 0, fecha_x0 - _TOL_TABLA_BENEFICIARIOS))
            fecha = _clean(value_between(line, fecha_x0 - _TOL_TABLA_BENEFICIARIOS, cuil_x0 - _TOL_TABLA_BENEFICIARIOS))
            # Filtro clave: en las tablas vacías, este rango de líneas tiene
            # notas al pie y textos de relleno (ej. "Si el espacio no fuera
            # suficiente..."), no filas de beneficiario -- una fila real
            # SIEMPRE trae una fecha con formato dd/mm/aaaa en su columna;
            # el texto de relleno, no.
            if not nombre or not fecha or not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", fecha):
                i += 1
                continue
            cuil = _clean(value_between(line, cuil_x0 - _TOL_TABLA_BENEFICIARIOS, pct_x0 - _TOL_TABLA_BENEFICIARIOS))
            pct = _clean(value_between(line, pct_x0 - _TOL_TABLA_BENEFICIARIOS, col_e_x0 - _TOL_TABLA_BENEFICIARIOS))

            # Una continuación real del nombre es corta (ej. "MERCEDES",
            # 1 palabra); una nota al pie es una oración larga -- se pone
            # un tope de 3 palabras para no confundirlas.
            siguiente = all_lines[i + 1] if i + 1 < fin else None
            if (
                siguiente is not None
                and siguiente["words"]
                and len(siguiente["words"]) <= 3
                and not any(w["text"].replace(",", "").replace(".", "").isdigit() for w in siguiente["words"])
                and siguiente["text"].strip() not in ("Primera Vida Asegurada", "Segunda Vida Asegurada")
            ):
                nombre = f"{nombre} {siguiente['text'].strip()}"
                i += 1

            contingentes.append({
                "nombre": _titlecase_es(nombre),
                "fecha": fecha,
                "cuil": cuil,
                "pct": pct,
                "vida": "Vida 2" if vida_asociada == "Segunda Vida Asegurada" else "Vida 1",
            })
            i += 1

    for n, b in zip((1, 2), contingentes):
        p = f"BENEFICIARIO CONTINGENTE {n} - "
        campos[p + "Nombre"] = b["nombre"]
        campos[p + "Fecha nacimiento"] = b["fecha"]
        campos[p + "CUIL/CUIT"] = b["cuil"]
        campos[p + "%"] = b["pct"]
        campos[p + "Vida asociada"] = b["vida"]

    return campos


def extract_solicitud(pdf_path):
    pages = load_lines(pdf_path)
    all_lines = _flatten(pages)
    campos = {}
    campos.update(extract_bloque_0(pages))
    campos.update(extract_bloque_2(pages))
    campos.update(extract_bloque_3(all_lines))
    campos.update(extract_bloque_4(all_lines))
    campos.update(extract_bloque_4b(all_lines))
    campos.update(extract_bloque_5(all_lines))
    campos.update(extract_bloque_6(all_lines))
    campos.update(extract_bloque_7(all_lines))
    campos.update(extract_bloque_8(all_lines))
    campos.update(extract_bloque_9(all_lines))
    campos.update(extract_bloque_10(all_lines))
    campos.update(extract_bloque_11(all_lines))
    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_solicitud.py <ruta_al_pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    campos = extract_solicitud(pdf_path)
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
