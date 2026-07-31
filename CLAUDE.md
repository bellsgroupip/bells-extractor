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
  1. Extractor real de la SOLICITUD por coordenadas (pdfplumber, agrupando por línea,
     SIN IA) que lea el PDF y devuelva los ~295 campos según el esquema de
     /base/Base_Combinada_Solicitudes_Zurich.xlsx (hoja Diccionario_Campos).
     EN PROGRESO: /extractor/extract_solicitud.py ya extrae completo el
     Bloque 0 (Documento) y el Bloque 2 (Solicitante/Tomador, 37 campos),
     validado contra las 3 solicitudes de /pdfs-prueba que tienen fila de
     referencia en Base_Combinada (~95% de coincidencia; las diferencias
     restantes son 3 campos derivados que no están como texto literal en
     el PDF — ver el docstring del script). Falta repetir el mismo patrón
     para los bloques 3, 4, 4b, 5 a 14.
  2. Extractor simple de DNI/AVAL (nombre, DNI, fecha de nacimiento).
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
