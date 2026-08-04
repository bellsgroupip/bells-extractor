"""
Extractor real de la "Solicitud de 3ro Pagador" (Personas Físicas y
Jurídicas), por coordenadas (pdfplumber), SIN IA. Este formulario se
adjunta a la SOLICITUD cuando quien paga la póliza no es el
Solicitante/Tomador (ver check_completitud.py / nodo "Consolidar y
Chequear" del workflow n8n, escenarios "Tercero Pagador físico/jurídico").

ESTADO ACTUAL / SUPUESTO IMPORTANTE:
El único ejemplo disponible hoy (pdfs-prueba/10_Tercero_Pagador_DS.pdf) es
la copia firmada por DocuSign del mismo Tomador (Abel Mendilaharzu, N° de
Solicitud 1354029) que ya tenemos como ejemplo de SOLICITUD -- con un
Pagador Persona Jurídica (una S.A. de la que el Tomador y el Solicitante
Conjunto son socios al 50%). NO hay ningún ejemplo real con Pagador
Persona Física, ni con el Tomador siendo Persona Jurídica -- los campos de
esas 2 combinaciones (Bloque 4 "Tomador Persona Jurídica" completo, y la
lectura de "Persona Física" en el Bloque 6 cuando el Pagador es una
persona) están escritos siguiendo el mismo patrón de coordenadas que sí
está calibrado, pero sin un ejemplo real que los ejercite. Este documento
tampoco tiene fila de referencia en Base_Combinada (no es parte del
Diccionario_Campos de la SOLICITUD) -- los nombres de campo de este
extractor son propios, no vienen de esa planilla.

Como en extract_solicitud.py, el checkbox "SI"/"NO" de las declaraciones
juradas (Sujeto Obligado / PEP) viene a veces con un espacio suelto
adentro ("S I" en vez de "SI") -- se reutiliza _si_no_juramento de ese
módulo, que ya tolera ese glitch.

Uso:
    python3 extract_tercero_pagador.py "../pdfs-prueba/10_Tercero_Pagador_DS.pdf"
"""

import json
import re
import sys

from pdf_layout import load_lines, find_line, value_between, word_x0, word_x1
from extract_solicitud import _titlecase_es, _grupos_si_no, _si_no_juramento, _value_after_label


def _clean(s):
    s = (s or "").strip()
    return s if s else None


def _flatten(pages):
    return [line for page in pages for line in page]


def _texto_entre(all_lines, ini, fin, contains):
    """find_line pero acotado a un rango [ini, fin) de líneas -- para no
    'pisar' con un match de una sección más adelante en el documento."""
    idx = find_line(all_lines, contains, start=ini)
    if idx is not None and idx < fin:
        return idx
    return None


# ---------------------------------------------------------------------
# Datos de una persona fisica (Tomador / Pagador / socio del Anexo 1) --
# mismo patrón de campos en las 3 secciones del formulario.
# ---------------------------------------------------------------------
# Etiquetas de columna que pueden quedar "sueltas" después de "Calle"
# cuando la fila de domicilio viene vacía (ej. "Calle Nº Piso Dpto." sin
# nada tipeado) -- si el "valor" leído es solo esto, no es un dato real.
_ETIQUETAS_DOMICILIO_RESTANTES = {"n", "nº", "n°", "piso", "dpto", "dpto."}


def _es_residuo_domicilio(valor):
    if not valor:
        return True
    return all(p.lower() in _ETIQUETAS_DOMICILIO_RESTANTES for p in valor.split())


def _sin_residuo_final(valor):
    """Saca las etiquetas de columna sueltas al FINAL del valor (ej.
    "...Mza 26 C Nº 14 Piso Dpto." -> "...Mza 26 C Nº 14" -- saca "Piso
    Dpto." porque no hay dato de piso/depto, pero conserva "Nº 14" porque
    ese sí es un dato real)."""
    if not valor:
        return valor
    palabras = valor.split()
    while palabras and palabras[-1].lower() in _ETIQUETAS_DOMICILIO_RESTANTES:
        palabras.pop()
    return " ".join(palabras) if palabras else valor


def _valor_incrustado_o_arriba(all_lines, idx, etiqueta):
    """Lee el valor que sigue a `etiqueta` en la misma línea; si no hay
    nada ahí (o lo que hay son etiquetas de columna sin dato, ver
    _es_residuo_domicilio), prueba con el texto de la línea INMEDIATAMENTE
    ANTERIOR. Este formulario es inconsistente: en algunas secciones el
    valor cae pegado a la etiqueta en la misma línea (ej. Domicilio del
    Pagador Persona Física) y en otras cae en el renglón de arriba, con
    la etiqueta sola abajo (ej. Domicilio del Tomador, Domicilio legal del
    Pagador Persona Jurídica) -- no se pudo determinar un patrón fijo por
    sección con un solo ejemplo, así que se prueban las 2 formas."""
    valor = _clean(_value_after_label(all_lines[idx], etiqueta))
    if valor and not _es_residuo_domicilio(valor):
        return _sin_residuo_final(valor)
    if idx > 0:
        return _clean(all_lines[idx - 1]["text"])
    return None


def _localidad_provincia(all_lines, idx):
    """Mismo problema que _valor_incrustado_o_arriba: "Localidad
    Provincia" a veces trae los 2 valores incrustados en su propia línea
    (ej. "Localidad DRAGONES Provincia Salta") y a veces el valor está
    solo en el renglón de arriba (ej. Tomador Física, "SALTA" sobre
    "Localidad Provincia" vacío)."""
    line = all_lines[idx]
    loc_fin = word_x1(line, "Localidad")
    prov_x0 = word_x0(line, "Provincia")
    if loc_fin is not None and prov_x0 is not None:
        localidad = _clean(value_between(line, loc_fin, prov_x0))
        prov_fin = word_x1(line, "Provincia")
        provincia = _clean(value_between(line, prov_fin, 10_000)) if prov_fin is not None else None
        if localidad or provincia:
            return " / ".join(v for v in (localidad, provincia) if v)
    if idx > 0:
        return _clean(all_lines[idx - 1]["text"])
    return None


def _dni_cuit_en_linea_o_arriba(all_lines, idx):
    """"<dni> <cuit>" puede venir en la MISMA línea que la etiqueta
    "DNI/LE/LC ... CUIL/CUIT/CDI ..." (Pagador Física/Jurídica) o en la
    línea de ARRIBA, con la etiqueta sola abajo (Tomador Física, Anexo 1
    -- ej. "32162123 20321621237" seguido de "DNI/LE/LC Nº CUIL/CUIT/CDI
    Nº")."""
    m = re.search(r"(\d[\d.]*)\D+(\d[\d-]*\d)", all_lines[idx]["text"])
    if m:
        return m.group(1), m.group(2)
    if idx > 0:
        m2 = re.match(r"(\d[\d.]*)\s+(\d[\d-]*\d)$", all_lines[idx - 1]["text"].strip())
        if m2:
            return m2.group(1), m2.group(2)
    return None, None


def _extraer_persona_fisica(all_lines, ini, fin, prefix, campos):
    """OJO: el formulario siempre trae las secciones "Persona Física" Y
    "Persona Jurídica" una atrás de la otra para el mismo rol (Tomador o
    Pagador) -- se completa UNA SOLA, la otra queda con las etiquetas
    impresas pero sin ningún dato tipeado. Por eso esta función corta
    apenas si "Nombre y Apellido" viene vacío: si no, terminaría leyendo
    texto de relleno (boilerplate de la sección vacía) como si fueran
    valores reales."""
    idx = _texto_entre(all_lines, ini, fin, ["Nombre", "y", "Apellido"])
    nombre = _clean(_value_after_label(all_lines[idx], "Apellido")) if idx is not None else None
    if not nombre:
        return
    campos[prefix + "Nombre y Apellido"] = _titlecase_es(nombre)

    idx = _texto_entre(all_lines, ini, fin, ["Lugar", "de", "nac."])
    if idx is not None:
        line = all_lines[idx]
        fin_lugar = word_x1(line, "nac.")
        inicio_fecha = word_x0(line, "Fecha")
        if fin_lugar is not None and inicio_fecha is not None:
            campos[prefix + "Lugar de nacimiento"] = _titlecase_es(
                value_between(line, fin_lugar, inicio_fecha)
            )
        m = re.search(r"nacimiento:\s*(\d{1,2})\s+(\d{1,2})\s+(\d{4})", line["text"])
        if m:
            dd, mm, yyyy = m.groups()
            campos[prefix + "Fecha de nacimiento"] = f"{dd.zfill(2)}/{mm.zfill(2)}/{yyyy}"

    idx = _texto_entre(all_lines, ini, fin, ["Nacionalidad"])
    if idx is not None:
        line = all_lines[idx]
        fin_nac = word_x1(line, "Nacionalidad")
        inicio_sexo = word_x0(line, "Sexo:")
        valor = None
        if fin_nac is not None and inicio_sexo is not None:
            valor = _clean(value_between(line, fin_nac, inicio_sexo))
        if not valor and idx > 0:
            valor = _clean(all_lines[idx - 1]["text"])
        campos[prefix + "Nacionalidad"] = valor
        grupos = _grupos_si_no(line, "Femenino", "Masculino")
        if grupos:
            _, femenino, masculino = grupos[0]
            campos[prefix + "Sexo - Femenino"] = femenino
            campos[prefix + "Sexo - Masculino"] = masculino

    idx = _texto_entre(all_lines, ini, fin, ["DNI/LE/LC", "N"])
    if idx is not None:
        dni, cuit = _dni_cuit_en_linea_o_arriba(all_lines, idx)
        campos[prefix + "DNI/LE/LC"] = dni
        campos[prefix + "CUIL/CUIT/CDI"] = cuit

    idx = _texto_entre(all_lines, ini, fin, ["Domicilio", "real"])
    if idx is not None:
        campos[prefix + "Domicilio real"] = _titlecase_es(
            _valor_incrustado_o_arriba(all_lines, idx, "Calle")
        )

    idx = _texto_entre(all_lines, ini, fin, ["Localidad", "Provincia"])
    if idx is not None:
        campos[prefix + "Localidad / Provincia"] = _titlecase_es(_localidad_provincia(all_lines, idx))

    idx = _texto_entre(all_lines, ini, fin, ["Estado", "civil"])
    if idx is not None and idx > 0:
        campos[prefix + "Estado civil"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))

    idx = _texto_entre(all_lines, ini, fin, ["Profesi", "oficio"])
    if idx is not None and idx > 0:
        campos[prefix + "Profesión"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))


# ---------------------------------------------------------------------
# Datos de una persona juridica (Tomador / Pagador)
# ---------------------------------------------------------------------
def _extraer_persona_juridica(all_lines, ini, fin, prefix, campos):
    """Misma salvedad que _extraer_persona_fisica: corta si "Razón
    Social" viene vacío (la sección Persona Jurídica de este rol no fue
    la utilizada)."""
    idx = _texto_entre(all_lines, ini, fin, ["Razón", "Social"])
    razon_social = _clean(_value_after_label(all_lines[idx], "Social")) if idx is not None else None
    if not razon_social:
        return
    campos[prefix + "Razón Social"] = _titlecase_es(razon_social)

    idx = _texto_entre(all_lines, ini, fin, ["CUIT/CDI"])
    if idx is not None:
        campos[prefix + "CUIT/CDI"] = _clean(_value_after_label(all_lines[idx], "CUIT/CDI"))

    idx = _texto_entre(all_lines, ini, fin, ["Domicilio", "legal"])
    if idx is not None:
        campos[prefix + "Domicilio legal"] = _titlecase_es(
            _valor_incrustado_o_arriba(all_lines, idx, "Calle")
        )

    idx = _texto_entre(all_lines, ini, fin, ["Localidad", "Provincia"])
    if idx is not None:
        campos[prefix + "Localidad / Provincia"] = _titlecase_es(_localidad_provincia(all_lines, idx))

    idx = _texto_entre(all_lines, ini, fin, ["Actividad", "principal"])
    if idx is not None and idx > 0:
        campos[prefix + "Actividad principal"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))


def extract_tercero_pagador(pdf_path):
    pages = load_lines(pdf_path)
    all_lines = _flatten(pages)
    n = len(all_lines)

    campos = {
        "N° de Solicitud": None,
        "Nombre del Tomador": None,
        "Nombre del Tomador Conjunto": None,
        "Tomador - Tipo": None,  # "Física" / "Jurídica"
        "Vínculo del Tomador con el Pagador": None,
        "Motivo del pago por Tercero": None,
        "Pagador - Tipo": None,  # "Física" / "Jurídica"
        "Pagador - ¿Existen socios con control societario o 10%+? - Sí": None,
        "Pagador - ¿Existen socios con control societario o 10%+? - No": None,
        "Pagador - ¿Sujeto Obligado ante la UIF? - Sí": None,
        "Pagador - ¿Sujeto Obligado ante la UIF? - No": None,
        "Pagador - ¿Cumple normativa PLA/FT? - Sí": None,
        "Pagador - ¿Cumple normativa PLA/FT? - No": None,
        "Pagador - ¿PEP? - Sí": None,
        "Pagador - ¿PEP? - No": None,
        "Pagador - PEP Motivo detallado": None,
        "Medio de pago": None,
        "N° de Tarjeta/CBU": None,
        "Firma Pagador - Aclaración": None,
        "Firma Pagador - Documento": None,
        "Productor Asesor - Nombre": None,
        "Productor Asesor - N° de Productor": None,
        "Productor Asesor - Matrícula S.S.N.": None,
    }
    for n_socio in (1, 2, 3, 4):
        prefix = f"SOCIO {n_socio} - "
        campos[prefix + "Nombre y Apellido"] = None
        campos[prefix + "DNI/LE/LC"] = None
        campos[prefix + "CUIL/CUIT/CDI"] = None
        campos[prefix + "Participación %"] = None

    # --- 2. Detalle de la Póliza
    idx = find_line(all_lines, ["N", "de", "Solicitud"])
    if idx is not None:
        m = re.search(r"Solicitud\s+(\d+)", all_lines[idx]["text"])
        if m:
            campos["N° de Solicitud"] = m.group(1)

    idx = find_line(all_lines, ["Nombre", "del", "Tomador"])
    if idx is not None and "Conjunto" not in all_lines[idx]["text"]:
        campos["Nombre del Tomador"] = _titlecase_es(
            _clean(_value_after_label(all_lines[idx], "Tomador"))
        )
    idx = find_line(all_lines, ["Nombre", "del", "Tomador", "Conjunto"])
    if idx is not None:
        campos["Nombre del Tomador Conjunto"] = _titlecase_es(
            _clean(_value_after_label(all_lines[idx], "corresponder)"))
        )

    # --- 3/4. Datos del Tomador (Física o Jurídica -- el formulario trae
    # las 2 secciones y solo una viene completa; se decide cuál según
    # dónde aparezca un "Nombre y Apellido"/"Razón Social" con datos).
    idx_3 = find_line(all_lines, ["Datos", "a", "completar", "por", "Personas", "Físicas"])
    idx_4 = find_line(all_lines, ["Datos", "a", "completar", "por", "Personas", "Jurídicas", "(Tomador)"])
    idx_6 = find_line(all_lines, ["6.", "Datos", "del", "Pagador"])
    fin_tomador = idx_6 if idx_6 is not None else n

    if idx_3 is not None:
        _extraer_persona_fisica(all_lines, idx_3, idx_4 or fin_tomador, "TOMADOR - ", campos)
    if idx_4 is not None:
        _extraer_persona_juridica(all_lines, idx_4, fin_tomador, "TOMADOR - ", campos)
    campos["Tomador - Tipo"] = (
        "Jurídica" if campos.get("TOMADOR - Razón Social") else "Física" if campos.get("TOMADOR - Nombre y Apellido") else None
    )

    # --- 5. Detalle: Vínculo del Tomador con el pagador / Motivo -- el
    # valor tipeado cae en el renglón ANTERIOR a su propia etiqueta (igual
    # patrón que "PEP - Motivo detallado" en extract_solicitud.py).
    idx = find_line(all_lines, ["Vínculo", "del", "Tomador", "con", "el", "pagador"], start=idx_4 or 0)
    if idx is not None and idx > 0:
        campos["Vínculo del Tomador con el Pagador"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))
    idx = find_line(all_lines, ["Motivo", "por", "el", "cual", "el", "pago"], start=idx_4 or 0)
    if idx is not None and idx > 0:
        campos["Motivo del pago por Tercero"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))

    # --- 6. Datos del Pagador (Física o Jurídica)
    # OJO: no basta con buscar la lista de palabras ["Datos", "a",
    # "completar", "por", "Persona", "Jurídica"] -- la intro de la
    # sección 6 ("...por Personas Físicas o representantes/apoderados de
    # Personas Jurídicas") también las contiene todas como substring
    # ("Persona" está en "Personas") y matchea primero por error. Se busca
    # la frase exacta "por Persona Jurídica" (singular), que solo aparece
    # en el título real de esa sub-sección.
    idx_pagador_juridica = find_line(all_lines, ["por Persona Jurídica"], start=idx_6 or 0)
    idx_anexo = find_line(all_lines, ["Anexo", "1"])
    fin_pagador = idx_anexo if idx_anexo is not None else n

    if idx_6 is not None:
        _extraer_persona_fisica(all_lines, idx_6, idx_pagador_juridica or fin_pagador, "PAGADOR - ", campos)
    if idx_pagador_juridica is not None:
        _extraer_persona_juridica(all_lines, idx_pagador_juridica, fin_pagador, "PAGADOR - ", campos)
    campos["Pagador - Tipo"] = (
        "Jurídica" if campos.get("PAGADOR - Razón Social") else "Física" if campos.get("PAGADOR - Nombre y Apellido") else None
    )

    idx = find_line(all_lines, ["Existen", "socios"], start=idx_pagador_juridica or 0)
    if idx is not None:
        grupos = _grupos_si_no(all_lines[idx], "SI", "No")
        if grupos:
            _, si, no = grupos[0]
            campos["Pagador - ¿Existen socios con control societario o 10%+? - Sí"] = si
            campos["Pagador - ¿Existen socios con control societario o 10%+? - No"] = no

    # --- Declaraciones juradas del Pagador (Sujeto Obligado / PLA-FT /
    # PEP) -- mismo patrón (y mismo glitch de "S I" suelto) que
    # extract_bloque_12 de extract_solicitud.py.
    idx = find_line(all_lines, ["soy", "Sujeto", "Obligado"], start=idx_6 or 0)
    if idx is not None:
        si, no = _si_no_juramento(all_lines[idx]["text"])
        campos["Pagador - ¿Sujeto Obligado ante la UIF? - Sí"] = si
        campos["Pagador - ¿Sujeto Obligado ante la UIF? - No"] = no

    idx = find_line(all_lines, ["cumplo", "con", "las", "disposiciones", "vigentes"], start=idx_6 or 0)
    if idx is not None:
        si, no = _si_no_juramento(all_lines[idx]["text"])
        campos["Pagador - ¿Cumple normativa PLA/FT? - Sí"] = si
        campos["Pagador - ¿Cumple normativa PLA/FT? - No"] = no

    # OJO: el checkbox "X SI NO" está en la línea que dice "...y que X SI
    # NO se encuentra incluido..." -- la línea siguiente, que menciona
    # "Personas Expuestas" literalmente, es la CONTINUACIÓN del párrafo
    # (no tiene el checkbox), así que hay que anclar en "se encuentra
    # incluido", no en "Personas Expuestas".
    idx_pep = None
    for i in range(idx_6 or 0, n):
        if "se encuentra incluido" in all_lines[i]["text"]:
            idx_pep = i
            break
    if idx_pep is not None:
        si, no = _si_no_juramento(all_lines[idx_pep]["text"])
        campos["Pagador - ¿PEP? - Sí"] = si
        campos["Pagador - ¿PEP? - No"] = no
        idx_motivo = find_line(all_lines, ["indicar", "detalladamente", "el", "motivo"], start=idx_pep)
        if idx_motivo is not None and idx_motivo > 0:
            anterior = all_lines[idx_motivo - 1]["text"].strip()
            if anterior and len(all_lines[idx_motivo - 1]["words"]) <= 6:
                campos["Pagador - PEP Motivo detallado"] = anterior

    # --- Anexo 1: socios (hasta 4 filas)
    if idx_anexo is not None:
        idx_header = find_line(all_lines, ["Nombre", "y", "Apellido"], start=idx_anexo)
        filas_inicio = []
        i = idx_header
        while i is not None and len(filas_inicio) < 4:
            filas_inicio.append(i)
            siguiente = find_line(all_lines, ["Nombre", "y", "Apellido"], start=i + 1)
            i = siguiente
        for k, idx_fila in enumerate(filas_inicio, start=1):
            prefix = f"SOCIO {k} - "
            fin_fila = filas_inicio[k] if k < len(filas_inicio) else n
            nombre = _clean(_value_after_label(all_lines[idx_fila], "Apellido"))
            campos[prefix + "Nombre y Apellido"] = _titlecase_es(nombre)
            if not nombre:
                continue
            idx_dni = find_line(all_lines, ["DNI/LE/LC"], start=idx_fila)
            if idx_dni is not None and idx_dni < fin_fila:
                dni, cuit = _dni_cuit_en_linea_o_arriba(all_lines, idx_dni)
                campos[prefix + "DNI/LE/LC"] = dni
                campos[prefix + "CUIL/CUIT/CDI"] = cuit
            idx_part = find_line(all_lines, ["Participación", "%"], start=idx_fila)
            if idx_part is not None and idx_part < fin_fila:
                valor = _clean(_value_after_label(all_lines[idx_part], "%"))
                if valor and valor.isdigit():
                    campos[prefix + "Participación %"] = valor

    # --- Medio de pago
    idx = find_line(all_lines, ["Medio", "de", "pago"])
    if idx is not None:
        line = all_lines[idx]
        fin_label = word_x1(line, "pago")
        inicio_venc = word_x0(line, "Vencimiento")
        if fin_label is not None and inicio_venc is not None:
            campos["Medio de pago"] = _clean(value_between(line, fin_label, inicio_venc))
        idx_nro = find_line(all_lines, ["N", "de", "Tarjeta/CBU"], start=idx)
        if idx_nro is not None and idx_nro > idx:
            numero = _clean(all_lines[idx_nro - 1]["text"])
            if numero and re.fullmatch(r"[\d.]+", numero):
                campos["N° de Tarjeta/CBU"] = numero

    # --- Firma del Pagador + Productor Asesor
    # Patrón de las 3 firmas (Solicitante/Tomador, Tomador Conjunto,
    # Pagador): <NOMBRE> / "Aclaración" (label) / <N° documento> / "Firma
    # del <Rol>... Tipo y N° de documento" (caption) -- el nombre está 3
    # líneas antes de la caption, no 2 (hay un renglón de más con la
    # palabra suelta "Aclaración").
    idx = find_line(all_lines, ["Firma", "del", "Pagador"])
    if idx is not None and idx >= 3:
        campos["Firma Pagador - Aclaración"] = _titlecase_es(_clean(all_lines[idx - 3]["text"]))
        campos["Firma Pagador - Documento"] = _clean(all_lines[idx - 1]["text"])

    idx = find_line(all_lines, ["Firma", "del", "Productor", "Asesor", "Aclaración"])
    if idx is not None and idx > 0:
        campos["Productor Asesor - Nombre"] = _titlecase_es(_clean(all_lines[idx - 1]["text"]))
    idx = find_line(all_lines, ["Matricula", "S.S.N."])
    if idx is not None and idx > 0:
        m = re.match(r"(\d+)\s+(\d+)", all_lines[idx - 1]["text"].strip())
        if m:
            campos["Productor Asesor - Matrícula S.S.N."] = m.group(1)
            campos["Productor Asesor - N° de Productor"] = m.group(2)

    return campos


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 extract_tercero_pagador.py <ruta_al_pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    campos = extract_tercero_pagador(pdf_path)
    print(json.dumps(campos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
