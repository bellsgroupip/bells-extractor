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
  (SOLICITUD/DNI/AVAL), rama de "no encontrado", descarga de los 3 archivos. La rama
  de "no encontrado" tiene 2 casos, ambos responden EN EL MISMO HILO del mail original
  (Gmail "Reply"): (a) sin link de Drive en el mail -- avisa que respondan adjuntando
  el link; (b) con link pero sin archivo de SOLICITUD en la carpeta -- avisa eso y
  además muestra TODOS los campos extraídos del DNI y el AVAL si esos archivos SÍ
  estaban en la carpeta (o "no se encontró el archivo" si no estaban). Para esto,
  "Solicitud Encontrada" (el IF que decide informe completo vs. aviso) se movió a
  DESPUÉS de la descarga+extracción (ya no antes) -- así el DNI/AVAL se descargan y
  extraen aunque falte la SOLICITUD, y "Consolidar y Chequear" quedó defensivo ante
  0 items de entrada (carpeta sin ningún documento reconocible). El archivo local del
  workflow (n8n/Bells_Revision_Solicitud.json) está reconciliado 1:1 con el workflow
  real en producción (2026-08-11) -- ya no hay divergencia entre ambos.
- Lo que falta programar de verdad (hoy son placeholders con datos de prueba):
  1. DONE: Extractor real de la SOLICITUD por coordenadas (pdfplumber, agrupando por
     línea, SIN IA) — /extractor/extract_solicitud.py ya cubre TODOS los bloques del
     Diccionario_Campos (0, 2, 3, 4, 4b, 5, 6, 6c, 7, 8, 9, 10, 11, 12, 13, 14),
     validado contra las 5 solicitudes de /pdfs-prueba que tienen fila de referencia
     en Base_Combinada (~90-95% de coincidencia en la mayoría; ver el docstring del
     script para los campos derivados/no calibrados que quedan pendientes y 2
     hallazgos de PDF con glitches de renderizado puntuales, no atribuibles al
     extractor). Los 4 campos derivados del Bloque 0 (cantidad de vidas aseguradas,
     tomador distinto de la vida asegurada, tipo de firma) ya están implementados —
     Bells Group confirmó las reglas el 2026-08-04 (el Tomador cuenta como "distinto"
     si no coincide con AL MENOS UNA Vida Asegurada presente; "Tipo de firma" se
     infiere de la marca de agua de DocuSign).
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
     documento, CUIT, y domicilio: Calle/Número/Localidad/Provincia) — nodo
     "Consolidar y Chequear" del workflow.
  6. Checklist "Validar DOC": DONE (best-effort) para los escenarios que Bells Group
     definió — ver nodo "Consolidar y Chequear". OJO: hoy solo verifica por NOMBRE DE
     ARCHIVO en la carpeta de Drive (no valida contenido ni a qué persona pertenece
     cada documento) — en escenarios con más de un DNI/AVAL requerido (Tomador ≠ Vida
     Asegurada) solo confirma que existe algún archivo de ese tipo, no uno por persona
     (queda marcado como "verificar manualmente"). "CSSEM en caso de corresponder"
     para Options quedó sin poder automatizarse: a diferencia de Invest Future, la
     Solicitud Options no trae un campo Sí/No de conformidad con la declaración de
     salud que lo dispare.

     DONE: extractor/extract_tercero_pagador.py extrae el formulario "Solicitud de
     3ro Pagador" (Tomador/Pagador Física o Jurídica, socios del Anexo 1,
     declaraciones PEP/UIF del Pagador, medio de pago, firmas) — calibrado contra el
     único ejemplo disponible (pdfs-prueba/10_Tercero_Pagador_DS.pdf, Pagador Persona
     Jurídica). Conectado al microservicio (tipo="tercero_pagador"), y al workflow
     completo: "Clasificar Archivos" lo detecta (patrón "tercero"/"3ro" + "pagador"
     en el nombre) y "Consolidar y Chequear" lo usa para dar el detalle exacto de
     documentación exigida según sea Física o Jurídica (en vez del aviso genérico de
     antes), cruza N° de Solicitud y nombre del Tomador contra la SOLICITUD, y suma
     las declaraciones PEP/UIF propias del Pagador a las reglas de negocio.
     HALLAZGO IMPORTANTE: Bells Group describió el escenario Tercero Pagador solo
     para Invest Future, pero el ejemplo real disponible (Zurich
     Options-AECLIF-1354029, Tercero Pagador Persona Jurídica) es una póliza
     OPTIONS — así que el chequeo de Tercero Pagador se armó para aplicar a AMBAS
     familias, no solo Invest Future.
     Sigue pendiente (necesita más cambios de infraestructura, no solo reglas de
     negocio): "Clasificar Archivos" solo toma 1 DNI y 1 AVAL por carpeta (no
     distingue de quién es cada uno), así que en escenarios con Tercero Pagador o
     Tomador ≠ Vida Asegurada el sistema sabe QUÉ documentos hacen falta pero no
     puede confirmar que el archivo correcto (de la persona correcta) esté
     efectivamente cargado.
  7. DONE: Reglas de negocio/compliance (PEP, Sujeto Obligado UIF por profesión) —
     mismo nodo. Profesiones y lógica exacta definidas por Bells Group (ver memoria
     `reglas_uif_pep_doc` en este proyecto).

     DONE: extractor/extract_cssem.py extrae del "Cuestionario de Salud Sin Examen
     Médico" (CSSEM) la Pregunta 7 (¿consultó a un médico / se sometió a algún examen
     o investigación médica?, con Razón/Fecha/Resultado si es "Sí") — calibrado
     contra el único ejemplo disponible (pdfs-prueba/CSSEM -DS-.pdf). Conectado al
     microservicio (tipo="cssem") y al workflow completo: "Clasificar Archivos" lo
     detecta (patrón "cssem"/"cuestionario"+"salud" en el nombre) y "Consolidar y
     Chequear" compara la fecha declarada en la Pregunta 7 contra la "Fecha de
     solicitud" (Bloque 0 de la SOLICITUD) — regla confirmada por Bells Group
     (2026-08-05): si la consulta/examen fue hecho DENTRO de los 3 meses de la fecha
     de la Solicitud, avisa en "Reglas importantes" que Zurich va a solicitar los
     análisis correspondientes; si fue hecho hace MÁS de 3 meses, no hace falta
     avisar (pueden no pedirlos). No cubre el resto del formulario (las otras 11
     preguntas de "Datos médicos") — no se pidió, y esta regla puntual es lo único
     que hoy se compara contra la SOLICITUD. CORRECCIÓN IMPORTANTE (Bells Group,
     2026-08-05): CSSEM es EXCLUSIVO de Options — Invest Future NUNCA lo requiere,
     sin importar la "Declaración de Salud" de la Vida Asegurada. La regla de la
     Pregunta 7 solo se evalúa si "Producto / Formulario" es "Zurich Options"; se
     sacó del todo el chequeo de CSSEM que antes existía en la rama Invest Future
     (disparaba con "Declaración de Salud 'no conforme'" — estaba mal, ya no está).

## Cómo probar
Los PDF de /pdfs-prueba son solicitudes reales ya usadas para armar la base de
referencia. Sirven para testear el extractor sin tener que esperar un mail nuevo.
