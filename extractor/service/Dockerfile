# Build desde la carpeta /extractor (no desde /extractor/service), porque
# necesita copiar pdf_layout.py y extract_solicitud.py que están un nivel
# arriba. Ver comando de build en README.md.
#
#   docker build -t bells-extractor -f service/Dockerfile .
#   (parado dentro de /extractor)

FROM python:3.11-slim

WORKDIR /app

# Binario de Tesseract (para extract_dni.py). El paquete de idioma NO se
# instala por apt: se usa el tessdata/ propio del repo (ver TESSDATA_PREFIX
# en extract_dni.py) para que el modelo de idioma sea siempre el mismo en
# dev y en el servidor, sin depender de qué versión traiga tesseract-ocr-spa.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Módulos del extractor (nivel /extractor)
COPY pdf_layout.py extract_solicitud.py extract_aval.py extract_dni.py check_completitud.py ./
COPY tessdata ./tessdata
# Servicio HTTP
COPY service/app.py ./

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
