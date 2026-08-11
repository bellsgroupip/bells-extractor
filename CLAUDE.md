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
     extract_dni.py (2026-08-11): calibrado contra 4 DNI reales (antes solo 1) —
     reveló que el extractor viejo fallaba en 3 de los 4 (no por bugs de lógica,
     sino porque son fotos/escaneos de peor calidad que el ejemplo original).
     Dos cambios de fondo: (a) el MRZ del dorso (código de máquina ICAO 9303)
     se usa como fuente PRIMARIA de Documento/Fecha de nacimiento/Apellido/
     Nombre — se lee mucho más limpio que las etiquetas impresas en fotos de
     baja calidad; las etiquetas del frente quedan como respaldo. (b)
     preprocesado de imagen (upscale 2x + gris + autocontraste + nitidez)
     para cuando sí hay que leer etiquetas impresas, y matching insensible a
     mayúsculas/acentos (cubre el formato viejo "libreta", con etiquetas en
     mayúscula fija en vez de bilingües). Campos nuevos agregados — Domicilio,
     Lugar de nacimiento, CUIL — salen del dorso, best-effort (calidad
     variable: en 2 de los 4 ejemplos reales el CUIL se lee bien, en los
     otros 2 no aparece con ninguna combinación de OCR probada; si no se
     encuentra queda en None, no se inventa ni se calcula). PENDIENTE: el
     formato "libreta" vieja (sin MRZ, ejemplo real disponible pero sin
     calibrar del todo) sigue sin extraer Apellido/Nombre/Documento de forma
     confiable — necesitaría más ejemplos de ese formato para calibrar mejor.
     El AVAL no es una plantilla única -- extract_aval.py reconoce 2 (ARCA
     Monotributo y ANSES CUIL/CUIT, calibradas cada una contra un ejemplo
     real en /pdfs-prueba) detectando el TÍTULO del documento antes de
     extraer nada. Si no reconoce la plantilla devuelve todos los campos en
     None -- FIX (2026-08-11) de un hallazgo real: un AVAL con una TERCERA
     plantilla no reconocida (otra Constancia de ARCA) generó errores falsos
     en el informe porque la versión vieja buscaba "CUIT:" en cualquier
     parte del PDF y agarraba texto de una tabla de impuestos no relacionada.
     Avisar apenas aparezca una plantilla nueva para calibrarla.
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
     DONE (2026-08-11): "Clasificar Archivos" ya no toma 1 solo DNI y 1 solo AVAL
     por carpeta — junta TODOS los que matcheen por nombre de archivo (dnis[]/
     avals[]). "Consolidar y Chequear" arma la lista de personas esperadas según la
     Solicitud (Tomador, Solicitante Conjunto, Vida Asegurada 1/2, y Pagador si hay
     Tercero Pagador Persona Física — fusionando roles que resultan ser la misma
     persona, ej. Tomador === Vida Asegurada 1 con el mismo DNI cuenta como una
     sola persona) y empareja cada DNI/AVAL extraído contra esa lista por N° de
     documento (o, para el AVAL, el DNI que el CUIT individual trae incrustado:
     TT-DDDDDDDD-V) con el nombre como respaldo. Reporta puntualmente de quién
     falta el DNI/AVAL, y si sobró algún archivo que no se pudo asociar a nadie
     (posible error de OCR/extracción o documento de una persona no declarada).
     Las reglas de consistencia SOLICITUD vs DNI/AVAL (fecha de nacimiento, nombre,
     N° de documento, CUIT, domicilio) ahora comparan específicamente contra el
     DNI/AVAL emparejado con el Tomador, no "el primero que aparezca" — más preciso
     incluso en el caso de una sola persona. Los socios del Anexo 1 (Tercero
     Pagador Persona Jurídica) quedan FUERA de este emparejamiento por persona —
     siguen como "verificar manualmente" (no se pidió, y son N personas variables
     sin un tope declarado en la Solicitud).
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
