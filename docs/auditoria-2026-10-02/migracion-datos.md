# Migraciones y datos (2026-10-02)

**Ninguna se ha aplicado a una base real.** Probadas sobre SQLite y MySQL 8.4 desechables (bases vacías creadas por el runner de pruebas).

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `ordenes 0036_auditoria_integridad` | expansiva | Tablas nuevas: CuentaCaja (CHECK saldo ≥ 0), ConsecutivoDocumento, ClaveIdempotencia, RegistroAuditoria. Columnas nulas: Caja.cuenta/comprobante_egreso/pago_recibo/reversa_de; ComprobanteEgreso.creado_por/aprobado_por/fecha_aprobacion; PagoReciboCaja.confirmado_por/fecha_confirmacion. `on_delete` CASCADE→PROTECT en ventas, órdenes, recibos, caja, egresos, referencias, pedidos de tela | Solo agrega; `on_delete` no cambia SQL (Django lo emula). Reversible con `migrate ordenes 0035` (borra solo lo nuevo) |
| `ordenes 0037_datos_caja_y_permisos` | datos, idempotente | Crea "Caja principal" con el saldo del último movimiento y le asigna los movimientos existentes; siembra RolePermission para roles sin fila con sus permisos efectivos previos; agrega CERRAR_CAJA a roles con acceso a caja | **Se detiene** si el último saldo de caja es negativo (no inventa un ajuste): correr `diagnostico_auditoria` y corregir con ajuste autorizado antes. Reversa = no-op (los datos sembrados se conservan; no cambian acceso) |
| `suministros 0032_auditoria_integridad` | sin SQL relevante | `on_delete` → PROTECT en Inventario.referencia, FacturaProveedor.proveedor, DetalleFactura.referencia, HistorialTraslado.item_inventario | — |
| `paginaweb 0004_bandeja_correos` | expansiva | Tabla CorreoSaliente | Reversible |
| `token_blacklist` (simplejwt) | expansiva | Tablas de tokens revocados | Reversible |

## Antes de aplicar en producción (cuando se autorice)

1. Respaldo verificado (el script `scripts/deploy/deploy_backend.sh` lo hace y comprueba el gzip).
2. En una **copia** restaurada: `python manage.py migrate` y `python manage.py diagnostico_auditoria --json`. Revisar: saldos negativos, pagos en efectivo confirmados sin ingreso, ventas con abono descuadrado, facturas de otro proveedor que su comprobante, ítems en varias remisiones activas, multiplicadores generales ≠ 1.
3. Cada excepción material se decide con su responsable (P06-04): causa, evidencia, corrección y reversión. No se reconstruyen movimientos sin respaldo documental.
4. `.env` del VPS con `DB_NAME` y `DB_USER` explícitos (H16) y `DJANGO_SECRET_KEY` de ≥ 32 bytes.
5. Programar `python manage.py reintentar_correos` en cron.

## Pendiente (P06)

- Ejecutar el diagnóstico sobre copia autorizada y registrar conteos aquí.
- Consolidar DetalleFactura↔Inventario, telas heredadas↔nuevas y `Venta.sede`↔`Sede` (P06-02): requiere decisión de fuente de verdad.
- Restricciones CHECK sobre filas históricas de Caja (importe ≥ 0) solo después de limpiar datos.

## P10-02 (2026-10-06)

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `suministros 0033_factura_fecha_pago_real` | expansiva | Columnas `fecha_pago_real` (nula) y `usa_aplicaciones` (falso) en FacturaProveedor; estado `parcial` en las opciones | Reversible a 0032. No rellena `fecha_pago_real` de facturas ya pagadas: su `fecha_pago` pudo haber sido sobrescrita con la fecha de pago y no se infiere la fecha límite original |
| `ordenes 0040_aplicaciones_egreso` | expansiva | Tabla AplicacionEgreso con CHECK importe > 0, anulación coherente y unicidad factura+comprobante | Reversible a 0039 solo si no hay abonos registrados (PROTECT) |
| `ordenes 0041_programacion_pagos` | expansiva | Tabla ProgramacionPago con CHECK de importe, ejecución con abono y cancelación con motivo | Reversible a 0040 si no hay programaciones |
| `ordenes 0042_bancos` | expansiva | Tablas CuentaBancaria, ExtractoBancario, MovimientoBancario, ConciliacionBancaria con unicidad por archivo y movimiento | Reversible a 0041 si no hay extractos importados |
| `ordenes 0043_movimiento_referencia` | expansiva | Columna `referencia` en MovimientoBancario (documento de la contraparte) | Reversible a 0042 |

## P11 (2026-10-06)

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `suministros 0034_recepcion_linea_pedido` | expansiva | Columna nula `detalle_pedido` (PROTECT) en Inventario | Reversible a 0033. No liga unidades históricas: las 565 de la copia siguen sin línea (`pedido` también estaba vacío); se ligan solo las que se registren o editen indicando la línea |
| `suministros 0035_novedad_entrega` | expansiva | Tabla NovedadEntrega con CHECK (un producto, cantidad ≥ 1) y unicidad por remisión | Reversible a 0034 si no hay entregas parciales registradas |

| `suministros 0036_movimientos_inventario` | expansiva | Tabla MovimientoInventario (JSON antes/después) y opción `devuelto_proveedor` en Inventario.disponibilidad | Reversible a 0035 si ninguna unidad quedó `devuelto_proveedor`. No crea movimientos para la historia anterior: la bitácora empieza al desplegar |
| `suministros 0037_conteos_inventario` | expansiva | Tablas ConteoInventario (un abierto por zona vía `zona_abierta` única) y LineaConteo (única por conteo y unidad) | Reversible a 0036 si no hay conteos |

| `suministros 0038_rechazos_recepcion` | expansiva | Tabla RechazoRecepcion (línea de orden de pedido, cantidad ≥ 1, motivo, usuario) | Reversible a 0037 si no hay rechazos registrados |

0034–0035 aplicadas en la copia de pruebas `u756180748_pruebasv3` el 2026-10-06, tras el respaldo verificado `respaldos_locales/pruebasv3_antes_migr_suministros0034_20261006_1335.sql.gz`. 0036–0037, tras `respaldos_locales/pruebasv3_antes_migr_suministros0036_*.sql.gz`. 0038 junto con P12/P13 (ver abajo).

## P13 (2026-10-06)

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `ordenes 0047_correccion_cliente` | expansiva | Tabla CorreccionCliente con cliente, usuario, fecha y JSON de valores originales/corregidos. Referencias PROTECT; sin relleno de históricos ni concesión de permisos | Probada desde cero en SQLite y MySQL 8.4 desechable. Antes de activar en staging/producción, respaldo y revisión de permisos. Revertir la migración eliminaría el historial: una vez haya correcciones, conservar tabla y respaldo al retirar la interfaz. No restaura automáticamente fichas normalizadas |

## P12 y aplicación en la copia (2026-10-06)

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `listaprecios 0011_lineacotizacion_costo_estimado_and_more` | expansiva | `LineaCotizacion.costo_estimado` y `VarianteProducto.descuento_maximo`, ambos nulos | Reversible a 0010 |
| `ordenes 0044_lineaventa_costo_estimado` | expansiva | `LineaVenta.costo_estimado` nulo | Reversible a 0043 |
| `ordenes 0045_comisiones` | expansiva | Tablas ReglaComision, PeriodoComision y LiquidacionVendedor | Reversible a 0044 si no hay reglas ni períodos |
| `ordenes 0046_casoposventa_seguimientoposventa_evidenciaposventa` | expansiva | Tablas CasoPosventa, SeguimientoPosventa y EvidenciaPosventa | Reversible a 0045 si no hay casos |
| `ordenes 0048_alter_evidenciaposventa_archivo` | sin SQL relevante | `EvidenciaPosventa.archivo` usa el almacén privado (`DJANGO_PRIVATE_MEDIA_ROOT`) | Reversible a 0047 |

`listaprecios 0011`, `suministros 0038` y `ordenes 0044–0048` se aplicaron sin errores en la copia de pruebas `u756180748_pruebasv3` (MariaDB 11.8) el 2026-10-06, tras el respaldo verificado `respaldos_locales/pruebasv3_antes_migr_ordenes0044_*.sql.gz`. La copia queda con toda la cadena de la rama aplicada.

## Eliminaciones y Nómina (2026-10-06)

| Migración | Tipo | Efecto | Riesgo / recuperación |
|---|---|---|---|
| `ordenes 0049_eliminar_modulos_fuera_de_alcance` | contractiva | Borra AplicacionEgreso, ProgramacionPago, PromesaPago, TurnoCaja, `Caja.turno` y Posventa (D-ALCANCE) | Tablas vacías en la copia y nunca desplegadas; la vuelta atrás es el respaldo previo |
| `suministros 0039_eliminar_conteos_y_abonos` | contractiva | Borra ConteoInventario/LineaConteo, `FacturaProveedor.usa_aplicaciones` y los estados «pago parcial» y «ajuste por conteo» | En la copia había 1 conteo de prueba; ninguna factura en «parcial» |
| `ordenes 0050_nomina` | mixta | Crea las tablas de Nómina y `Venta.valor_lista` (nulo); borra las tablas de comisiones viejas (en la copia solo había datos de prueba manual) | Respaldo `pruebasv3_antes_migr_ordenes0049_nomina_*` |
| `ordenes 0052_linea_sin_texto_proveedor` | expansiva | Añade `LineaVenta.sin_texto_proveedor` (booleano, falso por defecto). No toca datos | Aplicada en `pruebasv3` el 2026-10-07 tras `respaldos_locales/pruebasv3_antes_migr_ordenes0052_*.sql.gz`; vuelta atrás: `migrate ordenes 0051` |
| `ordenes 0053_tela_y_gestion_venta` | expansiva | Campos de tela en `LineaVenta`, `PedidoTela.venta`, `DetallePedidoTela.linea_venta`, `Venta.gestion_finalizada_en/por`. No toca datos; `estado_pedidos` se reutiliza como gestión finalizada | Aplicada en `pruebasv3` el 2026-10-08 tras `respaldos_locales/pruebasv3_antes_migr_ordenes0053_*.sql.gz`; vuelta atrás: `migrate ordenes 0052` |
| `ordenes 0054_tela_referencia_color_material` | expansiva | Renombra `LineaVenta.tela_nombre` → `tela_referencia` y añade `tela_color`, `tela_material` | Aplicada en `pruebasv3` el 2026-10-08 tras `respaldos_locales/pruebasv3_antes_migr_ordenes0054_*.sql.gz` (sin datos de tela aún); vuelta atrás: `migrate ordenes 0053` |
| `ordenes 0055_servicios_y_vinculos` | expansiva | `LineaVenta.tipo` (por defecto `producto`: las líneas existentes no cambian) y `DetallePedido.ignorar_vinculo` (falso) | Aplicada en `pruebasv3` el 2026-10-08 tras `respaldos_locales/pruebasv3_antes_migr_ordenes0055_*.sql.gz`; vuelta atrás: `migrate ordenes 0054` |
| `ordenes 0056_postferia_y_asistente` | expansiva | `Venta.es_postferia` (falso) y tablas `ConversacionAsistente`/`MensajeAsistente` (vacías) | Aplicada en `pruebasv3` el 2026-10-08 tras `respaldos_locales/pruebasv3_antes_migr_ordenes0056_*.sql.gz`; vuelta atrás: `migrate ordenes 0055` |
| `ordenes 0058_perfiles_y_aprendizaje_ia` | expansiva | Tablas `PerfilAsistente`, `DocumentoPerfilAsistente`, `AprendizajeAsistente` (vacías) y `ConversacionAsistente.perfil` (nulo) | Depende de 0056 (no de 0057). Aplicada **sola** en `pruebasv3` el 2026-10-08 (`migrate ordenes 0058_perfiles_y_aprendizaje_ia`) tras `respaldos_locales/pruebasv3_antes_migr_perfiles_ia0058_20261008_2014.sql.gz` (85 tablas, completo); tablas de Bancos intactas; vuelta atrás: `migrate ordenes 0056` |
| `suministros 0040_tela_en_productos_remision` | expansiva | `tela` (vacía) en `RemisionItemManual` y `RemisionInventarioTexto`; `descripcion` de este último admite vacío | Aplicada sola en `pruebasv3` el 2026-10-08 tras `respaldos_locales/pruebasv3_antes_migr_suministros0040_20261008_2107.sql.gz`; vuelta atrás: `migrate suministros 0039` |
| `ordenes 0060_nomina_cierre_por_asesor` | expansiva + datos | `AsesorCierre.estado` (abierto), `cerrado_por`, `cerrado_en`; los asesores de cierres ya cerrados pasan a cerrado con el mismo quién/cuándo | Depende de 0058. Aplicar con destino: `migrate ordenes 0060_nomina_cierre_por_asesor`; vuelta atrás: `migrate ordenes 0058` (los estados por asesor se pierden; el del cierre se conserva) |
| `ordenes 0061_merge_bancos_y_nomina` | sin operaciones | Une 0057 (Bancos, bloqueada) y 0060; reemplaza a `0059_merge_bancos_y_perfiles_ia`, que nunca se aplicó y se eliminó | Se aplicará cuando se autorice 0057; no ejecutar `migrate` sin destino mientras 0057 siga bloqueada |
