# Proyecto: Revisión automática de Solicitudes Zurich (Bells Group)

## Qué es esto
Automatización en n8n que, al llegar un mail con el link de Drive de un cliente nuevo,
busca la SOLICITUD, DNI y AVAL, extrae los datos de la SOLICITUD (PDF, siempre la misma
plantilla), los compara contra /base/Base_Combinada_Solicitudes_Zurich.xlsx, y devuelve
un informe con: errores del formulario, información incompleta, documentación faltante
en el Drive, y reglas de negocio importantes (ej. PEP, Sujeto Obligado UIF).

## Estado actual
- El workflow de n8n (/n8n/Bells_Revision_Solicitud.json) tiene armado y funcional:
  trigger de mail, extracción del link de Drive, listado y clasificación de archivos
  (SOLICITUD/DNI/AVAL), rama de "no encontrado", descarga de los 3 archivos.
- Lo que falta programar de verdad (hoy son placeholders con datos de prueba):
  1. DONE: Extractor real de la SOLICITUD por coordenadas (pdfplumber, agrupando por
     línea, SIN IA) — /extractor/extract_solicitud.py ya cubre TODOS los bloques del
     Diccionario_Campos (0, 2, 3, 4, 4b, 5, 6, 6c, 7, 8, 9, 10, 11, 12, 13, 14),
     validado contra las 5 solicitudes de /pdfs-prueba que tienen fila de referencia
     en Base_Combinada (~90-95% de coincidencia en la mayoría; ver el docstring del
     script para los campos derivados/no calibrados que quedan pendientes y 2
     hallazgos de PDF con glitches de renderizado puntuales, no atribuibles al
     extractor). Pendiente: revisar con Bells Group las 3 reglas de negocio que no
     se pueden completar por coordenadas simples (cantidad de vidas aseguradas,
     tomador distinto de la vida asegurada, tipo de firma).
  2. Extractor simple de DNI/AVAL (nombre, DNI, fecha de nacimiento) — ya armado en
     /extractor/extract_dni.py y /extractor/extract_aval.py.
  3. Motor de reglas de completitud (contra Diccionario_Campos, según el tipo de
     producto: Options 1 vida / Options 2 vidas / Invest Future).
  4. Reglas de consistencia interna del PDF (checkbox contradictorios, porcentajes
     de beneficiarios que no suman 100%, montos que superan límites, etc.)
  5. Reglas de consistencia cruzada SOLICITUD vs DNI/AVAL (nombre, DNI, fecha de
     nacimiento — ya hay un ejemplo funcional de esto en el nodo "Consolidar y
     Chequear" del workflow).
  6. Checklist "Validar DOC": qué documentos son obligatorios según el tipo de
     negocio (todavía sin definir el detalle completo).
  7. Reglas de negocio/compliance (ej. si la actividad es Escribano, exigir nota
     de Sujeto Obligado UIF) — todavía sin la lista completa de profesiones.

## Cómo probar
Los PDF de /pdfs-prueba son solicitudes reales ya usadas para armar la base de
referencia. Sirven para testear el extractor sin tener que esperar un mail nuevo.
