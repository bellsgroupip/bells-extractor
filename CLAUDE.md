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
  3. DONE: Motor de reglas de completitud (extractor/check_completitud.py) — cubre
     todos los bloques (0 a 14), con chequeo por fila de Beneficiarios y filtrado por
     familia Options/Invest Future donde corresponde.
  4. DONE: Reglas de consistencia interna del PDF (extractor/check_consistencia.py)
     — checkboxes contradictorios (reutiliza la lista de condicionales del motor de
     completitud, en la dirección opuesta), % de Beneficiarios Principales que no
     suman 100, y montos de Beneficios Adicionales que superan el Seguro de Vida
     Adicional (regla impresa literalmente en el PDF). A propósito NO incluye
     límites de edad por beneficio (son texto estático del PDF, no datos
     extraídos) ni % de incremento de primas (el propio checkbox del PDF ya
     restringe los valores posibles, no hay nada que validar ahí).
  5. DONE: Reglas de consistencia cruzada SOLICITUD vs DNI/AVAL (nombre, DNI, N° de
     documento, CUIT) — nodo "Consolidar y Chequear" del workflow.
  6. Checklist "Validar DOC": DONE (best-effort) para los escenarios que Bells Group
     definió — ver nodo "Consolidar y Chequear". OJO: hoy solo verifica por NOMBRE DE
     ARCHIVO en la carpeta de Drive (no valida contenido ni a qué persona pertenece
     cada documento) — en escenarios con más de un DNI/AVAL requerido (Tomador ≠ Vida
     Asegurada, Tercero Pagador) solo confirma que existe algún archivo de ese tipo,
     no uno por persona (queda marcado como "verificar manualmente"). Para Tercero
     Pagador tampoco se puede distinguir automáticamente persona física vs jurídica
     (la Solicitud no trae esos datos — están en un formulario aparte, "Solicitud de
     Tercero Pagador", que hoy no se descarga ni se extrae). Y "CSSEM en caso de
     corresponder" para Options quedó sin poder automatizarse: a diferencia de Invest
     Future, la Solicitud Options no trae un campo Sí/No de conformidad con la
     declaración de salud que lo dispare.
  7. DONE: Reglas de negocio/compliance (PEP, Sujeto Obligado UIF por profesión) —
     mismo nodo. Profesiones y lógica exacta definidas por Bells Group (ver memoria
     `reglas_uif_pep_doc` en este proyecto).

## Cómo probar
Los PDF de /pdfs-prueba son solicitudes reales ya usadas para armar la base de
referencia. Sirven para testear el extractor sin tener que esperar un mail nuevo.
