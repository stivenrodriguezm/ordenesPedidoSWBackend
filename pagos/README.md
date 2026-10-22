# Pagos bancarios de proveedores y nómina

Acceso operativo: **Comprobantes de egreso (CE)**. Pagos bancarios administra
beneficiarios/cuentas y consulta archivos; no inicia nuevas preparaciones.

## Uso

1. En Pagos bancarios → Beneficiarios y cuentas, buscar al proveedor, proveedor
   de telas o empleado. Agregar/editar/eliminar sus cuentas dentro de su ficha.
   La asociación se muestra expresamente y se guarda por ID, nunca por nombre.
   Eliminar desactiva la cuenta para nuevos pagos y conserva el historial.
2. La cuenta de origen pertenece a la empresa; se administra por separado.
3. En la tabla de CE, filtrar transferencias disponibles por banco destino
   (Davivienda, otros bancos o sin cuenta), elegir la cuenta de cada beneficiario
   y seleccionar una página o todos los resultados filtrados, hasta 500 CE.
   La cuenta principal o la única activa se propone sin guardar todavía.
4. Revisar los seleccionados: productos, costos, facturas, conceptos, importes,
   cuentas completas, titular bancario, identificación, origen y fecha. Generar
   y descargar guarda toda la agrupación atómicamente y produce el Excel.
   Los cambios de CE, productos o cuentas desde la revisión provocan 409;
   actualizar la revisión conserva la selección y permite verificar los cambios.
5. En el portal Davivienda seleccionar Nómina o Proveedores, la cuenta de origen
   indicada y **Excel estándar**. Después del resultado bancario, confirmar los
   pagos exitosos desde la agrupación de CE. Confirmación múltiple exige una
   referencia y utiliza el mismo servicio de confirmación individual de CE.
6. Reintentar solo pagos cuyo rechazo fue confirmado, reutilizando sus CE.
   No reintentar pagos pendientes/programados. Cada archivo conserva su versión.

Los CE antiguos de nombre libre permiten **Asociar beneficiario** explícitamente
a un proveedor o proveedor de telas registrado, sin inferir identidades por
coincidencia de nombre ni modificar importes. Sus cuentas se eligen desde CE.

Para nómina: vincular un usuario de la plataforma al perfil de pago, configurar
el neto habitual y sus cuentas. Los perfiles anteriores sin usuario conservan
su historia y muestran que falta vincularlo; nunca se reasignan por nombre.
Un perfil ya vinculado no puede cambiarse a otra persona conservando sus cuentas.
En CE → Preparar nómina se abre el mes y se ajustan pagos/cuentas individuales.
Los borradores mensuales programados también aparecen directamente en CE.
La preparación de pagos no recalcula prestaciones ni comisiones; los cierres
de asesores conservan su flujo previo y el neto se configura explícitamente.
Los permisos de nómina permiten abrir este espacio sin consultar CE de proveedores.

La programación crea un borrador por mes, por defecto el día 25 y con día
configurable 1–31. En meses más cortos usa su último día. No vuelve a calcular
meses existentes, no crea meses antiguos ni descarga/ejecuta/confirmar pagos
automáticamente. El motor muestra actividad y errores en Programación.
Al activarla después del día configurado se prepara el mes actual en el
siguiente ciclo, sin preparar los anteriores.

El motor persistente `ejecutar_automatizaciones_ia` invoca el programador cada
minuto. También se puede usar `preparar_pagos_nomina --continuo` como proceso
separado o `preparar_pagos_nomina` desde un scheduler diario. La restricción
única del mes y el bloqueo de ProgramacionNomina hacen idempotentes los ciclos.
No es necesario ejecutar ambos motores. Existe una plantilla systemd en deploy.

## Formato Davivienda y fuentes

Fuente: PDFs entregados por el usuario el 2026-10-20:
`FORMATO-EXCEL-ESTANDAR.pdf` pp. 2–4 y `TABLA-BANCOS.pdf` p. 2.
Se leyeron también `FORMATO-EXCEL-PERSONALIZADO.pdf` y `ARCHIVO-PLANO.pdf`.
Se implementa Excel estándar; no requiere personalizar columnas en el portal.

Una sola hoja `Pagos`, cabecera en fila 1, ocho columnas obligatorias en su
orden original y Referencia en la novena, siempre con el número de CE.
Se omiten correo y descripción opcionales para evitar columnas vacías.
Identificaciones y cuentas se conservan como texto, con sus ceros iniciales.
Valor es numérico sin separador de miles ni fórmulas. Nombre y apellido se
convierten a letras simples sin tildes, ñ ni signos en el archivo; el maestro
conserva el texto original. No se truncan números o nombres para hacerlos caber.

En el ERP se capturan/visualizan pesos COP enteros, `$3.000.000`. El límite por
CE sigue siendo el del modelo existente: hasta $99.999.999 para pesos enteros.
Los importes históricos con centavos se rechazan para exportar, sin reescribirlos.
El total de un archivo se suma con Decimal, sin ese límite por lote.

Las cuentas destino pueden ser de los bancos del catálogo suministrado,
incluido Bancolombia. La **cuenta origen y el exportador disponibles son
Davivienda**. Bancolombia como origen puede registrarse, pero se bloquea su
archivo hasta disponer de su especificación oficial y sus pruebas. Agregar un
adaptador en exportadores.py; nunca emitir un archivo Davivienda bajo su nombre.

## Integridad y permisos

- Descargar nunca paga CE, cierra nómina ni debita caja. Transferencias quedan
  `Por Confirmar Pago`. El PDF de CE conserva la regla previa de imprimir Pagado.
- Se bloquean lote, CE, empleados y cuentas dentro de transacción. Los cambios
  usan revisión optimista y la exportación compara la huella de los datos
  revisados, incluidos los maestros que pueden cambiar fuera del lote.
- Un CE no se reserva en dos lotes activos. Reintentos liberan solo pagos
  rechazados explícitamente y reutilizan su CE; confirmados se excluyen.
- Cada archivo se conserva con contenido original, SHA-256, origen y destinos.
  Repetir una descarga devuelve exactamente el mismo contenido y no crea CE.
- Anulación de archivo generado exige confirmar que no fue procesado ni quedó
  programado en el banco. Un lote con pagos confirmados no se anula; sus pagos
  fallidos se reintentan por separado. Corregir reutiliza CE y conserva versiones.
- Proveedores: ver egresos y ver todos los egresos; crear CE para preparar/editar,
  y exportar egresos para descargar. Nómina: ver/gestionar nómina. Confirmaciones
  siempre requieren aprobar egreso. No exponer cuentas a vendedores sin permiso.
- Auditoría de cuentas registra banco y últimos cuatro dígitos, no documentos
  completos. Archivos y snapshots financieros requieren el acceso restringido
  del módulo y copias de seguridad de la base de datos.

## Migraciones y comprobación

En pruebas se aplicaron exclusivamente ordenes.0078–0079 y pagos.0001–0005,
respaldando primero los CE. No aplicar un `migrate` general en la base compartida:
ordenes.0057 es una eliminación antigua pendiente fuera de este proyecto.
La migración de unión 0061 sigue aplazada y depende de 0079 para mantener esa
rama separada. Revisar el plan y limitar los destinos a ordenes.0079 (incluye pagos.0005).

Pruebas aisladas:

```
./testenv/bin/python manage.py test pagos ordenes.tests.test_egresos ordenes.tests.test_nomina --settings=lottusPedidos.settings_test
```

Verifican estructura y celdas del OOXML con un lector independiente, ceros
iniciales, códigos, exactitud monetaria, permisos, reintentos, rollback,
inmutabilidad y programación mensual. Son SQLite, no una prueba de carga de
bloqueos MySQL ni una certificación del portal bancario. La aceptación visual se
realiza con SQLite y datos ficticios, sin subir archivos al banco.
