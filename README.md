# Revisión automática de Solicitudes Zurich (Bells Group)

Automatización en n8n que revisa solicitudes de Zurich: al llegar el link de Drive de un
cliente nuevo, extrae los datos de la SOLICITUD (PDF) y los compara contra la base de
referencia (/base), devolviendo un informe de errores, información incompleta,
documentación faltante y reglas de negocio (PEP, Sujeto Obligado UIF, etc.).

El workflow de n8n está armado (/n8n) pero el extractor real de PDF, el motor de reglas
y las reglas de compliance todavía son placeholders — ver CLAUDE.md para el detalle.
