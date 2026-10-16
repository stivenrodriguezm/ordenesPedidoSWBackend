# P13: alcance contable y calidad de clientes

Fecha: 2026-10-06. Fuentes: respuesta del usuario en esta tarea, modelos de `ordenes`, `suministros` y `listaprecios`; [decisiones.md](decisiones.md), D06a–D06e. No se consultaron SIIGO ni documentos fiscales reales.

## Alcance acordado

El usuario confirma: «Se usa SIIGO pero no necesitamos exportar nada de momento». Se registra SIIGO como sistema contable indicado por el negocio. No se implementan exportaciones a SIIGO, conexión directa, sincronización ni emisión fiscal desde el ERP. La decisión es temporal y explícita; no equivale a una integración completada.

El inventario técnico disponible es:

| Documento/dato del ERP | Función observada en el código | Límite del inventario |
|---|---|---|
| `Cotizacion` / `LineaCotizacion` | Propuesta comercial y conversión a venta | No prueba emisión de una factura fiscal |
| `Venta` / `LineaVenta` | Compromiso comercial, productos, total, abono y saldo | No se verificó correspondencia con documentos SIIGO |
| `ReciboCaja` / `PagoReciboCaja` | Cobros, confirmaciones y movimientos de efectivo | La confirmación en ERP no demuestra contabilización externa |
| `ComprobanteEgreso` / `AplicacionEgreso` | Egresos y abonos a facturas de proveedores | El PDF conserva la regla «Pagado»; el estado operativo depende del medio y confirmación |
| `FacturaProveedor` | Compra/recepción y obligación con proveedor | No representa facturación fiscal de ventas; fecha límite distinta de pago real |
| `Caja` / `TurnoCaja` | Una caja principal, movimientos y arqueos | Cerrar turno no cambia saldo ni registra automáticamente una diferencia |
| `Remision` / `RemisionSuministro` | Documentación y operación de entregas | No se asume equivalencia con factura fiscal |

Falta contrastar con operadores quién emite, registra y concilia en SIIGO, qué documentos se corresponden y cómo se corrigen. No se inventan responsables, numeración, impuestos ni obligaciones legales. Si se solicita integración después, completar ese inventario y validar los requisitos aplicables antes de diseñar el contrato/sandbox. P13-04 sigue aplicando a los reportes y datos del ERP aunque no haya intercambio contable.

## Entrega local de calidad de clientes

Ruta `/calidad-clientes`, disponible con `VER_CLIENTES` y `VER_CALIDAD_CLIENTES`. Aplicar cambios exige además `EDITAR_CLIENTE` y `NORMALIZAR_CLIENTES`. Administrador conserva acceso total; los permisos nuevos no se conceden automáticamente a otros roles. El alcance usa `ventas_visibles`: vendedor limitado ve clientes de ventas propias/compartidas; no aparecen clientes ajenos ni sin ventas visibles. Otros roles conservan el alcance global establecido por esa función.

Se propone limpiar espacios en nombre, dirección, barrio y ciudad; separadores en teléfonos cuando son inequívocos; espacios exteriores en correo. No se deducen país, extensión ni dígitos faltantes, no se cambian cédula/NIT, mayúsculas del correo, saldos o relaciones de documentos. Cada propuesta debe superar el serializer existente. Todas las casillas empiezan vacías y solo se aplican las elegidas; el servidor recalcula los valores y registra los originales exactos, el usuario y la fecha en `CorreccionCliente`.

La vista previa firmada expira en 30 minutos; si la ficha cambia antes de guardar se responde 409 y la interfaz permite recargarla para revisar y seleccionar nuevamente. La escritura y el historial son atómicos y bloquean la fila; los reintentos con el mismo contenido/clave no duplican correcciones. El alcance se comprueba también antes de recuperar una respuesta idempotente. La bitácora general solo registra el identificador de revisión y los nombres de campos; los valores personales permanecen en el historial protegido y en la respuesta idempotente interna ya existente.

Los candidatos usan documento sin separadores (conservando letras/ceros y descartando identificadores de un carácter repetido), o nombre más teléfono/correo coincidentes. Se ignoran tildes solo para comparar nombres. Un nombre, teléfono o correo aislado no basta. Son sugerencias para revisión humana; no demuestran identidad. Una búsqueda conserva las coincidencias fuera del texto buscado dentro del mismo alcance. Se pagina el resultado; sobre 5000 clientes o grupos de más de 50 se rechaza con explicación, sin presentar resultados incompletos. Es un límite técnico provisional, no una cifra medida de operación.

La comparación de dos fichas muestra conflictos de campos y número de ventas visibles. **No ejecuta una fusión**, no elimina fichas ni traslada documentos. Conservar valores en historial permite reconstruir lo ocurrido, pero esta entrega no incluye un botón para deshacer cambios automáticamente.

## Continuación para otro agente

1. Preservar esta entrega y las decisiones del usuario. No reconstruir el historial de datos anterior a 0047 ni rellenar identidades por inferencia.
2. Completar P13-03 inventariando todas las relaciones a cliente: ventas, recibos por venta, cotizaciones, observaciones, posventa, remisiones y representaciones/PDF. Antes de trasladar referencias, asegurar que los documentos conservan la identidad/contacto original que necesiten mostrar; guardar snapshots o resolver una identidad canónica sin reescribir el documento histórico.
3. Para una fusión ejecutable, preparar vista previa de todas las referencias y conflictos, selección humana de ficha resultante y campos, motivo, permiso explícito, versión de ambos registros y auditoría reversible. Revalidar alcance dentro de la transacción y ordenar bloqueos. No borrar el origen ni basarse en nombre/contacto parcial. Probar dos fusiones simultáneas, solicitudes repetidas, cambio de ambas fichas y conservación de montos, vínculos y documentos impresos.
4. Continuar P13-04 desde [exportaciones-y-datos.md](exportaciones-y-datos.md): ya están validados localmente XLSX autorizado/auditado de clientes, historial comercial y notas por alcance, y CSV/totales/tasas de comisiones por usuario. Faltan exportaciones de ventas, recibos, egresos, inventario, impresión y acceso directo a adjuntos/evidencias de posventa. Auditoría acredita generación, no recepción del archivo. D06d conserva provisionalmente el directorio básico y la edición existente, pendiente de respuesta del usuario; no declarar revisadas todas las rutas de datos personales.
5. D06b sigue abierto: responsable de datos, plazos/causales de conservación, anonimización, solicitudes y excepciones documentales. No implementar purgas automáticas ni afirmar conformidad legal sin esa definición y verificación pertinente.
6. Aplicar 0047 primero en staging, asignar permisos, recorrer formato/historial/candidatos con datos ficticios en escritorio y móvil, y luego completar P14. Las pruebas de interfaz actuales son jsdom; no constituyen aceptación de operadores ni despliegue.
