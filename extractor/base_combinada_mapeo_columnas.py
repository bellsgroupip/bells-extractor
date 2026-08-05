"""
Genera el mapeo columna -> campo del extractor para
base/Base_Combinada_Solicitudes_Zurich.xlsx (hoja "Base_Combinada", 295
columnas), usado por el nodo "Mapear a Base Combinada" del workflow n8n
(n8n/Bells_Revision_Solicitud.json) para armar la fila que se agrega a la
planilla real de Bells Group después de cada SOLICITUD procesada.

Por qué existe este script (no es parte del pipeline de extracción, es
tooling de mantenimiento): las columnas "6. Beneficios Options (Vida 1)" y
"6b. Beneficios Options (Vida 2)" tienen el MISMO nombre de columna repetido
dos veces en la planilla (se distinguen solo por posición) mientras que
extract_solicitud.py, al ser un dict de Python, necesita nombres de campo
ÚNICOS -- por eso ahí usa el prefijo "VIDA ASEGURADA 1 - " / "VIDA ASEGURADA
2 - " que la planilla no tiene. Este script resuelve esa diferencia una sola
vez, por posición de columna, y deja el resultado listo para pegar como
array literal en el nodo de n8n.

Si la estructura de Base_Combinada_Solicitudes_Zurich.xlsx cambia (se
agregan/sacan/reordenan columnas), volver a correr esto y actualizar el
array MAPEO_COLUMNAS en el nodo "Mapear a Base Combinada" del workflow.

Uso:
    python3 base_combinada_mapeo_columnas.py
"""

import json

import openpyxl

_RUTA_BASE = "../base/Base_Combinada_Solicitudes_Zurich.xlsx"

# Rangos de columna (0-indexed, sobre la fila de headers reales -- fila 2
# del Excel, rows[1] con openpyxl) donde el nombre de columna es AMBIGUO
# (se repite para Vida 1 y Vida 2) -- fuera de estos rangos, el nombre de
# columna coincide 1:1 con una key del dict que devuelve extract_solicitud().
_RANGO_VIDA_1 = range(134, 158)  # "6. Beneficios Options (Vida 1)"
_RANGO_VIDA_2 = range(158, 182)  # "6b. Beneficios Options (Vida 2)"


def construir_mapeo():
    wb = openpyxl.load_workbook(_RUTA_BASE, data_only=True)
    ws = wb["Base_Combinada"]
    rows = list(ws.iter_rows(values_only=True))
    header = [h for h in rows[1] if h is not None]
    assert len(header) == 295, f"se esperaban 295 columnas, hay {len(header)} -- revisar la planilla"

    mapeo = []
    for i, colname in enumerate(header):
        if i == 0:
            # "Cliente / Archivo": no viene del extractor, se arma aparte
            # (nombre del Tomador, title-case) en el nodo de n8n.
            mapeo.append(None)
        elif i in _RANGO_VIDA_1:
            mapeo.append(f"VIDA ASEGURADA 1 - {colname}")
        elif i in _RANGO_VIDA_2:
            mapeo.append(f"VIDA ASEGURADA 2 - {colname}")
        else:
            mapeo.append(colname)
    return mapeo


if __name__ == "__main__":
    mapeo = construir_mapeo()
    print(json.dumps(mapeo, indent=2, ensure_ascii=False))
