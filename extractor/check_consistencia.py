"""
Motor de reglas de consistencia INTERNA de la SOLICITUD (punto 4 del
roadmap en CLAUDE.md) -- a diferencia de check_completitud.py (que
detecta CAMPOS VACÍOS que deberían tener dato), este motor detecta
CONTRADICCIONES entre campos que sí tienen dato.

Reglas implementadas:

1. Checkbox contradictorios: reutiliza la lista _CONDICIONALES de
   check_completitud.py (mismo criterio que ya usa para completitud) pero
   en la dirección opuesta -- si la pregunta habilitante quedó en "No
   marcado" y el campo dependiente TIENE un valor cargado, es una
   contradicción (la Solicitud dice "No" pero el PDF trae un
   detalle/monto igual).
2. Beneficiarios Principales: el % de cada Vida Asegurada (sumando los
   hasta 3 Beneficiarios Principales asociados a esa vida) tiene que
   sumar 100 -- validado contra los 5 PDF de prueba, siempre da 100 (ver
   _pct_beneficiarios_no_suman_100).
3. Montos de Beneficios Adicionales (Bloque 6/6c) no pueden superar el
   monto del "Seguro de Vida Adicional" -- es una regla literal impresa
   en el propio PDF ("Los montos consignados en cada Beneficio Adicional
   no podrán superar el monto del Seguro de Vida Adicional ni el máximo
   correspondiente a cada caso en particular"), validada contra los 3
   ejemplos reales que tienen montos cargados (siempre cumplen).

NO implementado a propósito, para no adivinar reglas de negocio que no
están claramente en el PDF ni confirmadas por Bells Group:
  - Límites de edad por beneficio (ej. "edad máxima para solicitarlo: 59
    años" en Hospitalización) -- son datos ESTÁTICOS impresos junto a
    cada checkbox, no campos extraídos; hardcodearlos acá los
    desincroniza en silencio si Zurich cambia esos límites en una
    revisión de plantilla.
  - % de incremento anual de primas (ver memoria "reglas-incremento-
    primas" de Bells Group: 0/3% Options, 0/5/10% Invest Future) -- no
    aporta una regla nueva porque el propio checkbox del PDF ya limita la
    elección a esos valores (no hay forma de que la extracción devuelva
    un valor inválido).

Uso:
    from extract_solicitud import extract_solicitud
    from check_consistencia import verificar_consistencia
    campos = extract_solicitud(pdf_path)
    inconsistencias = verificar_consistencia(campos)
"""

from check_completitud import _CONDICIONALES, _PREFIJOS, _vacio

_BENEFICIOS_ADICIONALES = (
    "Enfermedad Grave",
    "Renta Familiar",
    "Muerte Accidental",
    "Hospitalización",
    "Invalidez Total y Permanente",
    "Pérdida de Miembros",
    "Vida decreciente",
)


def _a_numero(s):
    """Convierte un monto/porcentaje tipeado en formato argentino ("." de
    miles, "," decimal, ej. "100.000" = 100000) a float. None si no se
    puede interpretar."""
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# Relleno tipeado a mano que NO cuenta como "dato cargado" para esta
# regla -- en los 5 PDF de prueba, "Actividad peligrosa - Detalle" trae
# literalmente "Ninguna" en vez de quedar vacío cuando la respuesta es
# "No" (el Solicitante lo interpreta como "completar igual, aclarando que
# no hay"). No es una contradicción real, es una forma válida de decir
# "no aplica".
_RELLENO_NO_APLICA = {"ninguna", "ninguno", "n/a", "no aplica", "-"}


def _es_relleno_no_aplica(valor):
    return isinstance(valor, str) and valor.strip().lower() in _RELLENO_NO_APLICA


def _contradicciones_checkbox(campos):
    """Reutiliza _CONDICIONALES de check_completitud.py: para cada par
    (campo dependiente, checkbox habilitante), si el habilitante está en
    "No marcado" pero el dependiente igual tiene un valor cargado, es una
    contradicción. Se prueba con cada prefijo conocido (Solicitante/Vida
    Asegurada) más sin prefijo, descartando combinaciones que no existen
    en el diccionario de campos (campos.get devuelve None sin error)."""
    producto = campos.get("Producto / Formulario")
    inconsistencias = []
    for sufijo_dependiente, sufijo_habilitante, familia in _CONDICIONALES:
        if familia is not None and familia != producto:
            continue
        for prefix in ("",) + tuple(_PREFIJOS):
            campo_dep = prefix + sufijo_dependiente
            if campo_dep not in campos:
                continue
            valor_hab = campos.get(prefix + sufijo_habilitante)
            valor_dep = campos.get(campo_dep)
            if valor_hab == "No marcado" and not _vacio(valor_dep) and not _es_relleno_no_aplica(valor_dep):
                inconsistencias.append(
                    f"Contradicción: '{prefix}{sufijo_habilitante}' está en 'No marcado' pero "
                    f"'{campo_dep}' tiene un valor cargado ({valor_dep!r})."
                )
    return inconsistencias


def _pct_beneficiarios_no_suman_100(campos):
    """El % de los Beneficiarios Principales de cada Vida Asegurada tiene
    que sumar 100 (validado contra los 5 PDF de prueba)."""
    inconsistencias = []
    for n in (1, 2):
        total = 0.0
        alguno = False
        error_parseo = False
        for b in (1, 2, 3):
            prefix = f"BENEFICIARIO PRINCIPAL {b} - "
            if campos.get(prefix + "Vida asociada") != f"Vida {n}":
                continue
            pct = campos.get(prefix + "%")
            if _vacio(pct):
                continue
            alguno = True
            numero = _a_numero(pct)
            if numero is None:
                error_parseo = True
            else:
                total += numero
        if error_parseo:
            inconsistencias.append(
                f"No se pudo interpretar alguno de los % de Beneficiarios Principales de la Vida Asegurada {n}."
            )
        elif alguno and abs(total - 100) > 0.01:
            inconsistencias.append(
                f"Los % de Beneficiarios Principales de la Vida Asegurada {n} suman {total:g} (debería sumar 100)."
            )
    return inconsistencias


def _montos_superan_limite(campos):
    """Los Beneficios Adicionales (Bloque 6 Options / 6c Invest Future)
    no pueden superar el monto del "Seguro de Vida Adicional" de esa
    misma Vida Asegurada (regla impresa literalmente en el PDF)."""
    inconsistencias = []
    for prefix in ("", "VIDA ASEGURADA 1 - ", "VIDA ASEGURADA 2 - "):
        monto_base_raw = campos.get(prefix + "Seguro de Vida Adicional - Monto")
        monto_base = _a_numero(monto_base_raw)
        if monto_base is None:
            continue
        for beneficio in _BENEFICIOS_ADICIONALES:
            monto_raw = campos.get(prefix + beneficio + " - Monto")
            monto = _a_numero(monto_raw)
            if monto is not None and monto > monto_base:
                inconsistencias.append(
                    f"'{prefix}{beneficio} - Monto' ({monto_raw}) supera el monto del Seguro de Vida "
                    f"Adicional ({monto_base_raw}) -- el PDF indica que los Beneficios Adicionales no "
                    f"pueden superarlo."
                )
    return inconsistencias


def verificar_consistencia(campos):
    """Devuelve una lista de mensajes describiendo contradicciones
    internas detectadas en los campos ya extraídos de la SOLICITUD."""
    inconsistencias = []
    inconsistencias.extend(_contradicciones_checkbox(campos))
    inconsistencias.extend(_pct_beneficiarios_no_suman_100(campos))
    inconsistencias.extend(_montos_superan_limite(campos))
    return inconsistencias
