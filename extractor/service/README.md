# Servicio del extractor (para conectar con n8n)

Por qué existe: el n8n de Bells Group (Cloud) no tiene el nodo "Execute
Command", así que no puede correr Python directo. Este servicio corre en tu
VPS, expone un endpoint HTTP, y el nodo **HTTP Request** de n8n le manda el
PDF descargado de Drive y recibe el JSON con los campos extraídos.

## 1. Requisitos en el VPS
- Docker instalado (`docker --version` para chequear).
- Un puerto libre expuesto a internet (o detrás de un reverse proxy con
  HTTPS, recomendado — ver punto 4).

## 2. Build y run

`tessdata/` (modelos de Tesseract para `extract_dni.py`) está en
`.gitignore` -- no viaja con `git clone`. Antes del primer build, copiar ahí
`eng.traineddata` y `spa.traineddata` (los mismos que usa el entorno de
desarrollo, para que el OCR se comporte igual en dev y en el servidor):

```bash
scp extractor/tessdata/*.traineddata usuario@servidor:/ruta/al/repo/extractor/tessdata/
```

Parado dentro de la carpeta `extractor` (no dentro de `extractor/service`):

```bash
cd extractor
docker build -t bells-extractor -f service/Dockerfile .

docker run -d \
  --name bells-extractor \
  -p 8000:8000 \
  -e EXTRACTOR_API_KEY="elegí-una-clave-larga-y-secreta-acá" \
  --restart unless-stopped \
  bells-extractor
```

`EXTRACTOR_API_KEY` es la clave que el nodo HTTP Request de n8n va a mandar
en el header `X-API-Key`. Si no la definís, el servicio queda sin
autenticación (solo para pruebas locales — no lo dejes así si el puerto
queda expuesto a internet).

## 3. Probarlo

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/extract \
  -H "X-API-Key: elegí-una-clave-larga-y-secreta-acá" \
  -F "tipo=solicitud" \
  -F "file=@/ruta/a/una/solicitud.pdf"
```

Debería devolver un JSON con `{"archivo": ..., "campos": {...}}`.

## 4. Exponerlo a n8n (recomendado: detrás de HTTPS)

Si el VPS ya tiene un reverse proxy (nginx, Caddy, Traefik) corriendo para
otros servicios (por ejemplo el mismo que sirve n8n.bellsgroup.com.ar), lo
más prolijo es agregar un subdominio tipo
`extractor.bellsgroup.com.ar -> localhost:8000` con certificado HTTPS, en
vez de pegarle directo por HTTP al puerto 8000. Así el nodo HTTP Request de
n8n apunta a `https://extractor.bellsgroup.com.ar/extract`.

Si no hay reverse proxy y se va a usar el puerto 8000 directo, como mínimo
hay que dejar `EXTRACTOR_API_KEY` configurada.

## 5. Nodo HTTP Request en n8n

Reemplaza al nodo `PLACEHOLDER Extraer Datos`:

- Method: `POST`
- URL: `https://<tu-dominio-o-ip>/extract`
- Send Headers: sí -> `X-API-Key` = la misma clave que pusiste en
  `EXTRACTOR_API_KEY`
- Body Content Type: `Form-Data` (multipart)
  - `file`: el binario del PDF descargado (viene del nodo "Descargar
    Archivo" anterior)
  - `tipo`: `solicitud` | `aval` | `dni` | `tercero_pagador` | `cssem`
    (según qué documento se esté mandando; ver "Armar Lista de Descargas"
    en el workflow)
- La respuesta trae los campos en `campos`, listos para usarlos en el nodo
  "Consolidar y Chequear".

## Estado del extractor (lo que este servicio devuelve hoy)

- `tipo=solicitud`: Bloque 0 (Documento) y Bloque 2 (Solicitante/Tomador,
  37 campos) — ver el docstring de `../extract_solicitud.py` para el
  detalle y lo que falta (bloques 3, 4, 4b, 5 a 14).
- `tipo=aval`: asume que el AVAL es la Constancia de Opción Monotributo de
  ARCA/AFIP (CUIT, nombre/razón social, domicilio, categoría, actividad,
  vigencia) — ver el docstring de `../extract_aval.py`. Si llega otro tipo
  de documento con ese nombre, no lo va a reconocer.
- `tipo=dni`: usa OCR (Tesseract) sobre el frente del DNI para leer
  Apellido, Nombre, Fecha de nacimiento y N° de Documento — ver el
  docstring de `../extract_dni.py`, en particular el supuesto sobre el
  recorte fijo del N° de Documento (calibrado sobre un solo DNI de
  ejemplo).

## Actualizar el servicio cuando el extractor sume más bloques

Cada vez que se agreguen bloques a `extract_solicitud.py` (o se ajuste
`extract_aval.py` / `extract_dni.py`), hay que reconstruir la imagen y
reiniciar el contenedor:

```bash
cd extractor
docker build -t bells-extractor -f service/Dockerfile .
docker stop bells-extractor && docker rm bells-extractor
docker run -d --name bells-extractor -p 8000:8000 \
  -e EXTRACTOR_API_KEY="la-misma-clave-de-antes" \
  --restart unless-stopped bells-extractor
```
