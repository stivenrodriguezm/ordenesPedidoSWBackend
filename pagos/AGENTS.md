# Reglas de pagos bancarios

Leer README.md antes de cambiar cuentas, lotes, exportación o programación.
Exportar nunca ejecuta transferencias ni confirma CE. Los importes son costos
de pago en COP enteros, y número de cuenta/documento siempre texto con sus ceros.
La exportación se valida contra la revisión del lote y la huella de cuentas/CE
revisados. No quitar bloqueos, transacciones, idempotencia o versiones de archivo.
Reintentar solo pagos explícitamente rechazados, reutilizando CE y omitiendo
confirmados. No reutilizar un formato Davivienda como si fuera Bancolombia.
No aplicar migraciones generales a pruebasv3: preservar fuera de alcance 0057.

El flujo de preparación vive exclusivamente en la tabla de CE. Pagos bancarios
es un directorio de beneficiarios/cuentas y un historial de archivos; los
borradores se continúan en CE. Mostrar Davivienda como nombre del banco.
Toda cuenta tiene un único dueño por ID: proveedor, proveedor de telas, perfil
de nómina vinculado a usuario, o la empresa (origen). No inferir asociaciones por
nombre ni reasignar historia/cuentas a otra persona. Quitar cuentas las desactiva.
La revisión previa incluye productos, costos, conceptos y cuentas completas;
validar huella de CE y sus cuentas bajo bloqueo antes de reservarlos en un archivo.
