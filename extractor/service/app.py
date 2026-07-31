"""
Microservicio HTTP que envuelve los extractores (pdf_layout.py /
extract_solicitud.py / extract_aval.py / extract_dni.py) para que n8n lo
pueda llamar con un nodo HTTP Request.

Por qué existe este servicio: la instancia de n8n de Bells Group (n8n Cloud)
no tiene disponible el nodo "Execute Command", así que no se puede correr
Python directo desde el workflow. Este servicio corre aparte (en el VPS del
cliente) y expone un endpoint REST; el nodo HTTP Request de n8n le manda el
PDF descargado de Drive y recibe el JSON con los campos extraídos.

Endpoints:
  GET  /health              -> chequeo simple, no requiere autenticación
  POST /extract             -> extrae los campos de un PDF
       form-data:
         file: el PDF (binario)
         tipo: "solicitud" | "aval" | "dni"
       header:
         X-API-Key: <EXTRACTOR_API_KEY> (ver variable de entorno)

Cómo correrlo (ver también /extractor/service/README.md):
    docker build -t bells-extractor -f extractor/service/Dockerfile extractor
    docker run -d --name bells-extractor -p 8000:8000 \
        -e EXTRACTOR_API_KEY=<elegir_una_clave_larga_y_secreta> \
        --restart unless-stopped bells-extractor
"""

import os
import tempfile

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from extract_solicitud import extract_solicitud
from extract_aval import extract_aval
from extract_dni import extract_dni
from check_completitud import verificar_completitud

app = FastAPI(title="Bells Group - Extractor Solicitudes Zurich")

API_KEY = os.environ.get("EXTRACTOR_API_KEY")  # si no se define, el servicio queda sin auth (solo para pruebas locales)

# tipo (form-data) -> función extractora. Ver el docstring de cada módulo
# para el detalle de qué campos devuelve y qué supuestos de formato asume.
EXTRACTORES = {
    "solicitud": extract_solicitud,
    "aval": extract_aval,
    "dni": extract_dni,
}


def _check_api_key(x_api_key: str | None):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="X-API-Key inválida o ausente")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    tipo: str = Form("solicitud"),
    x_api_key: str | None = Header(default=None),
):
    _check_api_key(x_api_key)

    extractor = EXTRACTORES.get(tipo)
    if extractor is None:
        raise HTTPException(
            status_code=400,
            detail=f"tipo='{tipo}' no soportado (usar solicitud, aval o dni)",
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    tmp_path = None
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        campos = extractor(tmp_path)
        respuesta = {"archivo": file.filename, "campos": campos}
        # El motor de completitud (check_completitud.py) hoy solo cubre los
        # campos de SOLICITUD (Bloques 0/2/3/4/4b) -- para DNI/AVAL no
        # aplica todavía.
        if tipo == "solicitud":
            respuesta["incompletos"] = verificar_completitud(campos)
        return respuesta
    except Exception as exc:  # noqa: BLE001 - queremos devolver el error al workflow
        raise HTTPException(status_code=500, detail=f"Error extrayendo el PDF: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
