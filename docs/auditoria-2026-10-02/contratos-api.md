# Cambios de contrato de la API (2026-10-02)

Compatibles con el frontend actual salvo donde se indica. Rama `auditoria-2026-10-02` de ambos repositorios.

> **Eliminados por decisión del usuario (2026-10-06, D-ALCANCE), no volver a crear:** `/api/cuentas-por-pagar/`, `/api/cartera/`, `/api/conciliacion/`, `/api/turnos-caja/`, `/api/posventa/…`, `/api/excepciones/tablero/` y `/api/suministros/conteos/`. Comisiones (`/api/comisiones/…`) se reemplazó por Nómina (`/api/nomina/…`).

## Errores

- Rechazos de negocio: `400` (`{campo: mensaje}` o `{"detail": ...}`), `403` sin permiso, `404` objeto fuera de alcance, `409` conflicto (relación histórica protegida, clave de idempotencia con otro contenido, configuración de precios incompleta). Ningún 4xx deja escrituras parciales.
- Borrar algo con documentos asociados (`ProtectedError`) responde `409` en vez de `500`.

## Idempotencia

Cabecera opcional `Idempotency-Key` (≤ 100 caracteres) en `POST /api/caja/`, `POST /api/comprobantes-egreso/crear/`, `POST /api/recibos-caja/crear/`. Misma clave + mismo cuerpo → misma respuesta, sin repetir efectos. Mismo usuario + operación + clave con otro cuerpo → `409`. Sin cabecera, comportamiento anterior. El frontend la envía y la reutiliza al reintentar el mismo contenido.

## Endpoints

| Endpoint | Cambio |
|---|---|
| `GET /api/health/` | **Nuevo**. `200 {"status":"ok","database":"ok"}` o `503`. Sin autenticación ni datos sensibles |
| `POST /api/logout/` | **Nuevo**. `{refresh}` → revoca el refresh token |
| `POST /api/token/refresh/` | Devuelve también un `refresh` nuevo (rotación); el anterior queda revocado. Rechaza cuentas desactivadas |
| `POST /api/caja/` | Solo `tipo` ∈ {ingreso, egreso}; `valor` > 0; `total_acumulado` del cliente se ignora |
| `POST /api/caja/cierre/` | Exige CERRAR_CAJA; `descuadre` ≥ 0 (signo en `signo`); no altera el saldo |
| `POST /api/comprobantes-egreso/crear/` | Valida existencia, proveedor y estado de cada factura; importe dentro de la regla provisional D02; `id` por contador bloqueado (sigue desde 3001 / máximo existente) |
| `PUT /api/comprobantes-egreso/<id>/editar/` | Cambiar `estado` sin APROBAR_EGRESO → `403` |
| `PATCH /api/recibos-caja/pagos/<id>/confirmar/` | Un pago en Efectivo confirmado crea su ingreso de caja (antes no, si había cambiado de medio). Doble confirmación: un solo efecto |
| `GET /api/listar-pedidos/`, `GET /api/ordenes-pedido/...`, `/completo/`, `/pedidos/<id>/detalles/` | `costo` ausente sin VER_COSTOS_ORDEN; rutas alternativas con el mismo alcance (404 fuera de él) |
| `POST /api/ordenes-pedido/` | Detalles: referencia existente y del proveedor de la orden, cantidad 1–10000. Errores por fila: `{"detalles": {"producto_2": {...}}}` |
| `POST/PATCH /api/detalles-pedido/` | Serializador de escritura validado (antes 500) |
| `GET /api/proveedores/` | Orden estable (`nombre_empresa`, `id`) y `?search=`. El frontend recorre todas las páginas |
| `DELETE /api/usuarios/<id>/` | Desactiva (204) en vez de borrar |
| `GET/PUT /api/role-permissions/` | GET sin escrituras; POST/DELETE no disponibles; `role` de solo lectura |
| `GET /api/user/` | `permissions` = permisos efectivos (misma función que la API) |
| `GET /api/suministros/inventario/...`, `/grupos/` | Sin VER_COSTOS_INVENTARIO no incluyen costos |
| `POST/PATCH /api/suministros/facturas/` | `productos` tipados; fila inválida → 400 con `{"productos": {"producto_N": ...}}`; Σ costo×cantidad (+ entregados no enviados) = `valor`. **Edición**: cada fila puede traer `id_referencias` (lista) para actualizar esas unidades en sitio; las omitidas se quitan solo si no tienen entregas, remisiones, traslados ni costos adicionales |
| `DELETE /api/suministros/facturas/<id>/` | `409` si tiene pago o mercancía comprometida/con historia |
| `POST /api/suministros/remisiones/` | Ítems de ventas ajenas o stock no disponible → 400; reserva verificada bajo bloqueo |
| Lista de precios | Acciones no listadas exigen EDITAR_LISTA_PRECIOS; no se puede desmarcar el general (reemplazar marcando otro); valor > 0; sin general → `409` accionable |
| `POST /api/paginaweb/pqrs/` | `correo_confirmacion`: `enviado` / `pendiente`; mensaje honesto |
| `POST .../pqrs/<id>/responder/` | `correo_respuesta`: estado real del envío |
| `POST /api/listaprecios/upload-foto/` | Formato real por contenido, ≤ 15 MB, ≤ 12000 px por lado, ≤ 10 archivos |
| Códigos de inventario nuevos | Prefijo + consecutivo (continúa tras el mayor existente, puede tener 5+ dígitos); códigos y QR existentes no cambian |
| `GET /api/ordenes-pedido/` | Orden estable `-id` (antes sin orden: la primera página dependía de la base) |
| Paginación (`page_size` > 100) | El máximo sigue en 100; el frontend recorre `page=1..n` para catálogos y exportaciones en vez de pedir 9999 |
| `POST /api/listaprecios/cotizaciones/` | **Nuevo** (P09-01). Cotización persistente en servidor; numeración `COT-XXXX` con `siguiente_consecutivo`; exige al menos 1 línea; calcula subtotales y total con descuento; control de concurrencia optimista (`version`) |
| `PATCH /api/listaprecios/cotizaciones/<id>/` | **Nuevo** (P09-01). Edición de borrador/emitida; `409` ante versión desfasada; `400` si está aceptada o convertida (invariante de congelamiento) |
| `POST /api/listaprecios/cotizaciones/<id>/cambiar-estado/` | **Nuevo** (P09-01). Transiciones de estado (`emitida`, `aceptada`, `rechazada`, etc.) |
| `POST /api/listaprecios/cotizaciones/<id>/convertir-a-venta/` | **Nuevo** (P09-04). Transición atómica e idempotente a `Venta` + `LineaVenta` (P09-03); resuelve cliente; no duplica si ya fue convertida |
| `GET /api/ventas/<id>/` | `VentaDetalleSerializer` incluye `lineas` propias y `cotizaciones` vinculadas (expediente P09-05) |
| `POST /api/ventas/crear/` | Soporta `lineas` estructuradas para crear `LineaVenta` directamente y `cotizacion_id` opcional |

## Recepción y entrega (P11-01, P11-03, 2026-10-06)

- **Factura (`POST/PATCH /api/suministros/facturas/`)**: cada producto acepta `detalle_pedido` (id de la línea de la orden de pedido, alias `detalle_pedido_id`). Debe ser del mismo proveedor y de una orden no anulada; la venta de la orden se hereda (una venta distinta = 400) y, si no se envía disponibilidad, queda `cliente`. Las unidades quedan con `pedido` y `detalle_pedido`. Si una línea quedaría con más unidades que las pedidas: 400 y nada se guarda. `null` desliga. Sin el campo, igual que antes.
- **Orden de pedido**: cada línea trae `recibidas` (unidades ligadas) en `/api/ordenes-pedido/`, `/api/ordenes-pedido/<id>/completo/` y `/api/pedidos/<id>/detalles/`. La orden pasa sola de `pendiente`/`en_proceso`/`finalizado` a `recibido` cuando todas sus líneas están completas (`RegistroAuditoria` `orden_pedido.recibida`); nunca baja sola. `PATCH /api/detalles-pedido/<id>/` no admite `cantidad` menor que lo recibido (400) y borrar una línea con recibidas da 409.
- **Confirmar entrega (`PATCH /api/suministros/remisiones/<id>/`, `estado: "finalizada"`)**: `no_entregados` opcional, lista de `{inventario: "<id>"}` o `{item_manual: <id>, cantidad}` con `motivo` (`faltante`, `rechazado`, `danado`, `otro`; `otro` exige `detalle`). Lo no entregado vuelve a `cliente`/`exhibicion`; con pendientes se ignora `cerrar_ventas`. Si todo quedaría sin entregar: 400 (registrar `devuelta`). `no_entregados` en otra transición: 400. La respuesta trae `no_entregados` con `motivo_label`.
- **`GET /api/suministros/remisiones/datos-ventas/`**: cada línea de pedido agrega `recibidas` y `cantidad_por_remisionar` (pedida − recibida como unidad − ya remisionada neta de lo no entregado). `remision_previa` solo cuando lo remisionado cubre el resto.

## Movimientos de inventario (P11-02, 2026-10-06)

- **Disponibilidad nueva** `devuelto_proveedor`. `PATCH /api/suministros/inventario/<id>/` y las filas de factura rechazan (400):
  - poner a mano `por_despachar`, `despachado` o `devuelto_proveedor`;
  - cambiar disponibilidad o venta de una unidad en remisión activa;
  - reactivar una unidad devuelta.
  
  Cada cambio de disponibilidad, zona, estado físico o venta deja un `MovimientoInventario`.
- `GET /api/suministros/inventario/<id>/movimientos/` (VER_INVENTARIO): lista `[{tipo, tipo_label, fecha, usuario, antes, despues, motivo, documento}]`, del más reciente al más antiguo, máximo 200. `documento` es `factura:<id>` o `remision:<id>`.
- `POST /api/suministros/inventario/<id>/devolver-proveedor/` (EDITAR_ITEM_INVENTARIO): recibe `{motivo}` (obligatorio). Devuelve 409 si ya fue devuelta, si va en una remisión activa o si está despachada o entregada. La línea de orden de pedido ligada deja de contarla como recibida.
- `DELETE /api/suministros/inventario/<id>/`: 409 si la unidad tiene movimientos de proceso, traslados, remisiones, costos adicionales o ya fue entregada.
- `POST /api/ordenes-pedido/`: cada detalle acepta `linea_venta`, que debe ser de la venta de la orden (si no, 400). Los detalles devuelven `linea_venta`.

## Bancos (P10-03, 2026-10-06)

| Endpoint | Contrato |
|---|---|
| `GET /api/bancos/cuentas/` | VER_BANCOS. Cuentas (número enmascarado), pendientes, último extracto y formatos soportados |
| `POST /api/bancos/importar/` | + CONCILIAR_BANCOS. Multipart `archivo` (≤ 5 MB), `formato` (`bancolombia_xlsx`, `davivienda_pdf`), `complemento` opcional (plano de Davivienda del mismo mes), `confirmar`. Sin confirmar: vista previa (200) sin escribir. Confirmado: 201. 400 si el archivo no cuadra; 409 si ya se importó |
| `GET /api/bancos/movimientos/?cuenta=` | `estado` (pendiente por defecto, conciliado, explicado, todos), `tipo`, `desde`, `hasta`, `search`; `totales` del filtro y `por_estado` |
| `GET /api/bancos/movimientos/<id>/sugerencias/` | `exactos` (mismo valor, ±3 días), `otros` (para lotes), `recomendado` (id o null) |
| `POST …/<id>/conciliar/` · `/explicar/` · `/deshacer/` | + CONCILIAR_BANCOS. `{pagos | egresos, motivo_diferencia?}` · `{categoria, nota?}` · `{motivo}`. No cambia el estado de cobros ni egresos |
| `GET /api/bancos/sin-banco/?cuenta=&desde=&hasta=` | Cobros de ese banco y egresos por transferencia sin movimiento conciliado |

## Precios, márgenes y simulación (P12-01, 2026-10-06)

| Endpoint | Contrato |
|---|---|
| `POST /api/listaprecios/multiplicadores/<id>/simular/` | EDITAR_LISTA_PRECIOS. Body: `{nuevo_valor: decimal > 0}`. Responde `{multiplicador_id, multiplicador_nombre, valor_actual, valor_nuevo, variantes_afectadas, ejemplos: [{variante_id, variante_nombre, linea_nombre, categoria_nombre, grupo_nombre, precio_actual, precio_nuevo, diferencia}]}` |
| `POST/PUT/PATCH /api/listaprecios/cotizaciones/` | Valida que `descuento` no supere el tope ponderado del documento (25% por defecto, o `descuento_maximo` de la variante). Calcula y congela `costo_estimado` por línea |
| `POST /api/listaprecios/cotizaciones/<id>/convertir-a-venta/` | Prorratea el descuento del documento proporcionalmente entre las líneas. Cada `LineaVenta` recibe su descuento asignado, subtotal neto y `costo_estimado` congelado. Garantiza `Σ subtotal == venta.valor_total` |
| `POST /api/ventas/crear/` | Valida el descuento de cada línea contra el tope de la variante (o 25% por defecto). Calcula y congela `costo_estimado` |
| Permiso `VER_MARGENES` | `SinMargenSinPermisoMixin` en `CotizacionSerializer`, `LineaCotizacionSerializer`, `VentaSerializer`, `LineaVentaSerializer` y `VentaDetalleSerializer`. Sin este permiso, `costo_estimado`, `margen` y `margen_total` se omiten de la respuesta |

## Calidad de clientes (P13-03, 2026-10-06)

Todas las rutas requieren autenticación, `VER_CLIENTES` y `VER_CALIDAD_CLIENTES`. El alcance se deriva de `ventas_visibles`: clientes ajenos y sin ventas visibles quedan fuera para el vendedor limitado. Las lecturas no escriben. Paginación habitual: 25 por página, máximo 100 mediante `page_size`.

| Ruta bajo `/api/calidad-clientes/` | Método | Contrato |
|---|---|---|
| raíz | GET | `buscar` (máximo 100 caracteres), `page`, `page_size`; devuelve `count/next/previous/results` con cliente, cambios `{campo: {antes, despues}}` y `version` firmada |
| `{id}/` | GET | Misma vista previa de una ficha; 404 si no pertenece al alcance |
| `candidatos/` | GET | Grupos `{id, razones, clientes}`, paginados, con `clientes_revisados`; compara todo el alcance y muestra grupos con al menos una ficha que cumple `buscar`. 413 si supera 5000 fichas o una coincidencia incluye más de 50; no trunca silenciosamente |
| `comparar/?origen=1&destino=2` | GET | Dos IDs distintos y visibles; `origen`, `destino`, `conflictos`, `ventas_visibles`, `puede_fusionar: false`, advertencia; 400 si son iguales. No mueve referencias |
| `{id}/normalizar/` | POST | Añade EDITAR_CLIENTE + NORMALIZAR_CLIENTES. JSON `{version, campos: ["telefono1"]}`. Solo campos propuestos, únicos y selección no vacía. El servidor calcula el valor; no acepta modificar identidad. Respuesta `{revision, cliente, cambios, version}` |
| `{id}/historial/` | GET | Lista paginada de `{id, cliente, fecha, responsable, cambios}` con originales; no hay edición/borrado del historial |

`version` está ligada al ID y contenido de la ficha, firmada con expiración de 1800 segundos. Token alterado, vencido o ficha modificada → 409, sin escrituras. Corrección, historial y bitácora se guardan en la misma transacción con bloqueo de cliente. `Idempotency-Key` permite recuperar el éxito de la misma solicitud; se comprueba el alcance antes de devolver también esa respuesta. Clave reutilizada con otro contenido → 409. `RegistroAuditoria` registra `cliente.normalizar`, revisión y nombres de campos, sin copiar valores personales. La tabla protegida `CorreccionCliente` y las respuestas internas de idempotencia sí contienen datos personales y quedan sujetas a D06b.

Migración requerida: `ordenes/0047_correccion_cliente.py`. No asigna permisos ni cambia clientes existentes. No hay exportación a SIIGO ni endpoint de fusión.

## P13-04: clientes, historial y exportación de comisiones (2026-10-06)

Sin nuevas migraciones ni permisos. Políticas provisionales D06d/D06e; otras rutas pendientes en `exportaciones-y-datos.md`.

| Ruta | Contrato actualizado |
|---|---|
| `GET /api/clientes/` | Mantiene directorio básico global con `VER_CLIENTES`. Filtros `query` y `search` (nombre/documento parcial o ID exacto; máximo 255 caracteres cada uno), `cedula` exacta (máximo 20), combinados por AND. Paginación existente; añade `exportacion: {permitida: boolean, alcance: "global" / "propias_compartidas"}`. Respuesta `no-store` |
| `GET /api/clientes/<id>/` | Ficha básica con `VER_CLIENTES`, `no-store`. `PUT` conserva permiso/política existente de edición mientras se confirma D06d; no significa que todas las rutas de edición estén cerradas |
| `GET /api/clientes/<id>/ventas-observaciones/` | `VER_CLIENTES`; ventas anidadas solo con permiso de ventas (incluye alias propios/todas) y su alcance. Notas solo si cliente pertenece al alcance comercial. Mantiene claves existentes y añade `puede_agregar_observaciones` y `historial_limitado`. Cliente fuera del alcance comercial conserva identificación básica y listas vacías; no revela cuántas compras ajenas tiene. `no-store` |
| `POST /api/clientes/<id>/observaciones/anadir/` | `VER_CLIENTES` y cliente en alcance; fuera de alcance 404. Mantiene validación de texto y autor de sesión |
| `PUT/DELETE /api/observaciones-cliente/<id>/` | `VER_CLIENTES`, cliente en alcance y regla existente de autor/`EDITAR_CLIENTE`. Rechazo antes de escribir/borrar; cliente fuera de alcance 404 incluso si el actor fue autor |
| `POST /api/clientes/exportar/` | `VER_CLIENTES` + `EXPORTAR_CLIENTES`. Filtros en query string iguales al directorio, sobre `clientes_visibles`; cuerpo vacío. Ignora `page/page_size`: archivo completo dentro del filtro/alcance, hasta 10 000 clientes. XLSX `Clientes.xlsx`, nueve columnas básicas explícitas y tipos de texto; excluye historia, ventas y notas. Cero resultados produce encabezados. GET no admitido (405) |
| `GET /api/comisiones/periodos/<id>/exportar_csv/` | Se conserva GET por compatibilidad. `VER_COMISIONES`; global con `GESTIONAR_COMISIONES` o `ve_todas_las_ventas`, personal en los demás casos. CSV UTF-8 BOM, separador `;`, todo el período autorizado; no aplica búsqueda visual por nombre ni permite ampliar alcance con `vendedor`. Límite 10 000 filas de detalle + resumen por liquidación; encabezados no cuentan |
| Períodos, liquidaciones y reglas de comisiones | Totales/conteos de período calculados con liquidaciones autorizadas. Detalle ajeno 404; filtro `vendedor` solo para alcance global. `porcentajes_especificos` de reglas contiene solo la tasa propia si el usuario es limitado. `PUT/PATCH` de período exige `GESTIONAR_COMISIONES` y rechaza período cerrado con 400 |

Exportaciones: permiso faltante 403; filtro inválido o texto no representable en XML de XLSX 400; exceso de límite 413; fallo de auditoría 500 sin entregar archivo. Errores siguen contrato JSON existente incluso cuando el cliente pidió Blob. Archivo exitoso responde `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` y `Content-Disposition: attachment`. No se escriben archivos temporales de clientes en disco.

Eventos: `clientes.exportar` (`ReporteClientes`, `directorio`) con formato, campos, filas, alcance y huellas HMAC de filtros válidos; `comisiones.exportar` (`PeriodoComision`, ID) con formato, filas, liquidaciones y alcance. Usuario/fecha los registra `RegistroAuditoria`. No se copian datos personales ni búsquedas en texto a esos eventos. Se registra generación, no recepción: un nuevo intento exitoso crea otro evento, sin idempotencia de descarga. La exportación no es un cierre contable inmutable.

Texto CSV se protege frente a prefijos `=`, `+`, `-`, `@`, también tras blancos o caracteres invisibles; los importes `Decimal` mantienen el signo. XLSX usa tipo texto explícito, sin transformar fórmulas aparentes en fórmulas ejecutables ni perder ceros/prefijos telefónicos.

## Nómina (D12a, 2026-10-06)

GET exige VER_NOMINA; cualquier cambio exige GESTIONAR_NOMINA. Las operaciones sobre un cierre devuelven el cierre completo.

- **Configuración:** `GET/PUT /api/nomina/config/` con `{tabla_comision: [[descuento %, comisión %]…], abono_minimo_pct, bonificacion_pct, ventas_desde, dia_pago_basico, pago_nomina}`.
- **Datos fijos por asesor:** `GET /api/nomina/asesores/` y `PATCH /api/nomina/asesores/<usuario>/` con `{salario_basico, meta, activo}`.
- **Cierres:**
  - `GET /api/nomina/cierres/` devuelve `{periodo_sugerido, cierres}`.
  - `POST` con `{fecha_inicio, fecha_fin, nombre?}` crea y calcula el cierre (201).
  - `GET/DELETE /api/nomina/cierres/<id>/`. Borrar solo se permite en borrador; si no, 409.
  - `POST /api/nomina/cierres/<id>/regenerar|cerrar|reabrir/`. `reabrir` exige `{motivo}` y devuelve 409 si hay un cierre posterior cerrado.
- **Cierre:** `{…, resumen, asesores: [{id, asesor, nombre, salario_basico, meta, ventas_periodo, cumple_meta, cumple_meta_manual, totales, lineas}]}`.
  - **`totales`:** `salario_basico`, `comisiones`, `bonificaciones`, `ajustes`, `total_nomina`, `comisiones_pendientes`, `bonificaciones_pendientes`.
  - **Cada línea:** `tipo` (`comision`, `bonificacion` o `ajuste`), `venta`, `cliente`, `fecha_venta`, `estado_venta`, `valor_venta`, `participantes`, `base`, `precio_lista`, `descuento_pct`, `porcentaje`, `valor`, `abono_pct`, `pagar`, `motivo_pendiente`, `editada`, `nota` y `causada_en`.
- **Asesor en el cierre:** `PATCH /api/nomina/asesores-cierre/<id>/` con `{salario_basico, meta, cumple_meta_manual (null|true|false), nota}`. Recalcula las bonificaciones.
- **Ajustes:** `POST /api/nomina/asesores-cierre/<id>/ajustes/` con `{descripcion, valor}`. Valor negativo descuenta; cero es 400.
- **Líneas:** `PATCH /api/nomina/lineas/<id>/` con `{precio_lista, porcentaje, valor, pagar, nota, descripcion}`.
  - El precio de lista recalcula el descuento, el % y el valor, y se guarda en la venta salvo `guardar_en_venta: false`.
  - La línea queda marcada como editada y "Recalcular" no la cambia.
  - `DELETE` solo borra ajustes.
  - Con el cierre cerrado, cualquier cambio da 409.
- **Venta:** `valor_lista` (nulo) en el listado, el detalle, la creación y la edición. Solo lo cambia quien tiene EDITAR_VENTA.

## Productos de la venta (P15, D15a, 2026-10-07)

| Ruta | Método | Contrato |
|---|---|---|
| `/api/ventas/{id}/productos/` | GET | `{venta, revision, confirmados, valor_total, valor_lista, lineas[], pedidos_sin_vincular[]}`. Cada línea trae `texto_proveedor`, `sin_texto_proveedor`, `texto_cliente`, `referencia`, `por_pedir`, `pedidas`, `pedidos[]` |
| `/api/ventas/{id}/productos/` | POST | `{revision, lineas: [...]}` con `Idempotency-Key`. **Ya no se envían** `precio_unitario`, `descuento`, `fecha_compromiso` ni `especificaciones` (se ignoran). `referencia` puede omitirse: el servidor la infiere. Sin `texto_proveedor` ni `sin_texto_proveedor: true` → 400 `{"texto_proveedor": ...}` (salvo producto de bodega). Al guardar, `valor_lista` = Σ precio de lista y el valor de la venta se reparte por proporción de lista. Revisión vieja → 409 |
| `/api/ventas/{id}/productos/calcular/` | POST | Precio de lista de una línea (sin guardar) |
| `/api/productos-venta/catalogo/` | GET | Búsqueda paginada; con `id` devuelve además `referencias` (hasta 5 sugeridas, la primera es la propuesta) |
| `/api/ventas/{id}/productos/pedidos/` | POST | Crea OP por proveedor desde lo pendiente; si la línea tiene "No aplica", las especificaciones del pedido quedan en `-` |

**2026-10-08:** en `/api/ventas/` y `/api/ventas/{id}/editar/`, `valor_lista` es de solo lectura (se ignora si se envía). Cambiar `valor_total` reparte el nuevo valor entre los productos y sube `revision_productos`; `valor_lista` y `productos_confirmados` se conservan. En productos, `adicionales` (recargos) ya no exige `motivo_precio`; solo `precio_lista_override` lo exige.

**Chat — asesor gerencial (D16, 2026-10-08).** Todas exigen `USAR_ASISTENTE_IA`; cada usuario ve solo lo suyo.

| Ruta | Método | Contrato |
|---|---|---|
| `/api/asistente/estado/` | GET | `{configurado, modelo}` |
| `/api/asistente/conversaciones/` | GET | Últimas 50: `[{id, titulo, actualizada}]` |
| `/api/asistente/conversaciones/{id}/` | GET / DELETE | Conversación con `mensajes: [{id, rol, texto, estado, error, consultas, modelo, creado}]` / borrarla |
| `/api/asistente/preguntar/` | POST | `{texto (≤4000), conversacion?}` → **202** `{conversacion, pregunta, respuesta}` con la respuesta en `estado: procesando`; 503 sin `GEMINI_API_KEY`; 429 tras 40 preguntas/hora; 409 si la conversación aún espera una respuesta |
| `/api/asistente/mensajes/{id}/` | GET | Mensaje con `estado` (`procesando`/`listo`/`error`) y `consultas` hechas hasta el momento; la página lo consulta cada 1,5 s |

**Perfiles de IA y aprendizaje (D18, 2026-10-08).** `USAR_ASISTENTE_IA` en todas; crear/editar/borrar perfiles y documentos exige además `GESTIONAR_PERFILES_IA`.

| Ruta | Método | Contrato |
|---|---|---|
| `/api/asistente/estado/` | GET | Agrega `puede_gestionar_perfiles`, `areas: [{id, nombre, descripcion}]`, `iconos`, `colores`, `limites: {conocimiento_caracteres, archivo_bytes}` |
| `/api/asistente/preguntar/` | POST | Agrega `perfil?` (id de un perfil **activo**; solo al crear la conversación, luego se usa el de la conversación). Perfil inactivo/inexistente → 400 |
| `/api/asistente/conversaciones/…` | GET | Cada conversación trae `perfil: {id, nombre, rol, icono, color} \| null`; los mensajes del asistente traen `valoracion` (`gusto`/`mejora`/null), `comentario` y `notas: [{id, texto}]` |
| `/api/asistente/perfiles/` | GET / POST | Lista (quien no gestiona ve solo activos) / crear `{nombre, rol, instrucciones (40–12.000), icono, color, areas[], activo}` → 201; errores por campo (400) |
| `/api/asistente/perfiles/{id}/` | GET / PUT / PATCH / DELETE | Perfil con `documentos[]` y `conocimiento_caracteres`. Borrar conserva sus conversaciones (pasan a la IA general) y elimina documentos y aprendizajes |
| `/api/asistente/perfiles/{id}/documentos/` | POST multipart `archivo` | `.md/.markdown/.txt/.pdf` ≤ 10 MB con texto legible → 201 `{id, nombre, tipo, tamano, caracteres, recortado, vista_previa}`; 400 si no hay texto, PDF protegido o supera la capacidad del perfil |
| `/api/asistente/perfiles/{id}/documentos/{doc}/` | GET / DELETE | Texto extraído completo (lo que lee la IA) / quitarlo |
| `/api/asistente/mensajes/{id}/valorar/` | POST | `{valoracion: gusto\|mejora\|null, comentario?}`; una valoración por respuesta propia y lista (null la quita) → mensaje actualizado; 404 si no es propia |
| `/api/asistente/mensajes/{id}/notas/` | POST | `{texto}` → 201 mensaje con `notas` |
| `/api/asistente/aprendizajes/` | GET `?perfil=` / POST | Lo aprendido del usuario con ese perfil (sin `perfil` = IA general) / nota directa `{texto, perfil?}` |
| `/api/asistente/aprendizajes/{id}/` | PATCH / DELETE | `{activo?, texto?}` (pausar/editar) / olvidar; solo los propios |

`/api/ventas/`, `/api/ventas/{id}/`, `/api/ventas/crear/` y `/api/ventas/{id}/editar/` aceptan/devuelven `es_postferia` (D17).

**Tela y gestión (D15b, 2026-10-08):**

| Ruta | Método | Contrato |
|---|---|---|
| `/api/ventas/{id}/productos/` | GET/POST | Cada línea acepta/devuelve `tela_modo` (`''`, `no_aplica`, `incluida`, `aparte`), `tela_material` (`tela`/`cuero`; por defecto según el grupo de precio), `tela_referencia`, `tela_color`, `tela_proveedor` (ProveedorTela), `tela_cantidad`; además devuelve `tela_proveedor_nombre`, `tela_unidad` (`m`/`dm`), `tela_pedidos[]`, `tela_orden` (OP del producto), `tela_direccion_sugerida` y `grupo_es_cuero`. La respuesta trae `gestion: {estado, dias_limite, pendientes[], finalizada_en, finalizada_por}`. Cambiar la tela de un producto con tela ya pedida → 400 |
| `/api/ventas/{id}/productos/` | POST | (2026-10-08, D15c) Cada línea acepta `tipo` (`producto` por defecto, `transporte`, `articulo`, `ajuste`); en los no-producto: `producto_nombre` (descripción) y `precio_lista_override` (valor; negativo solo en `ajuste`), `cantidad` solo en `articulo`. Un producto incompleto responde 400 con `{"lineas": {i: {campo: mensaje}}}` (campos: `referencia`, `tela_modo`, `tela_referencia`, `tela_color`, `tela_proveedor`, `tela_cantidad`, `texto_proveedor`, `texto_cliente`). `precio_producto` (calcular) no exige esos datos. El valor de la venta menor que servicios+ajustes → 400 |
| `/api/ventas/{id}/productos/vincular-pedidos/` | POST | `vinculos: [{detalle, linea}]`; `linea: null` = "no es de un producto de esta venta" (`ignorar_vinculo`). La referencia del pedido puede diferir de la del producto |
| `/api/ventas/{id}/productos/pedidos/` | POST | (2026-10-08) Acepta `ordenes: [{proveedor, fecha_esperada?, observacion, tela?}]` por proveedor; sin `tela`, se calcula (Sin tela / Por pedir / Pedida). Responde además `detalle: [{id, proveedor, tela, fecha_esperada}]`. La representación de productos trae `proveedor` por línea y `fecha_entrega`, `vendedor_nombre`, `es_feria_hogar` |
| `/api/pedidos-telas/` | POST | El mismo de /telas. Al ligar productos, la OP cuya tela estaba "Por pedir"/"Pendiente" pasa a "Pedida" cuando ya se pidió la de todos sus productos. Acepta además `venta` y, en cada detalle, `linea_venta`. Los productos deben ser de esa venta, visible para quien pide, y sin tela ya pedida (400 si no). El producto queda con lo pedido (material por el prefijo `[CUERO]`, referencia y color de `Ref - Color: X`, proveedor y cantidad) y la venta sube de revisión. (Reemplaza al endpoint `/productos/telas/`, que se retiró el mismo día) |
| `/api/ventas/{id}/gestion/` | POST | `{revision, accion: finalizar|reabrir}`; `EDITAR_PRODUCTOS_VENTA`, `EDITAR_VENTA` o `EDITAR_ESTADO_PEDIDOS_VENTA`. Finalizar con pendientes → 409 con la lista |
| `/api/ventas/`, `/api/ventas/{id}/` | GET | Nuevo campo `gestion` (`pendiente`/`atrasada`/`finalizada`/`null` si anulada) |

`/api/calidad-clientes/?con_correcciones=1` devuelve solo fichas con cambios propuestos (usado por la pestaña "Fichas por corregir").

**2026-10-08 (remisiones y nómina):**
- `/api/suministros/remisiones/datos-ventas/`: cada ítem de `inventario` y de `pedidos` trae `tela` (texto «Tela Lino · color arena»; vacío si no lleva).
- `/api/suministros/remisiones/` (POST/PATCH): `items_manuales[].tela` y `telas_inventario: {id_referencia: texto}`; la respuesta trae `items_manuales[].tela` e `inventario_items_detalle[].tela_remision`.
- `GET /api/nomina/lineas/{id}/venta/` (VER_NOMINA): `{venta, productos[], totales{precio_lista, precio_venta, productos_sin_precio_lista, lista_cuadra, venta_cuadra}, pagos[]}`.
- Nómina por asesor: `POST /api/nomina/asesores-cierre/{id}/cerrar/` y `/reabrir/` (GESTIONAR_NOMINA) → cierre completo. Cada asesor trae `estado` (`abierto`/`cerrado`), `cerrado_por`, `cerrado_en` y en `totales`: `ventas_con_lista`, `lista_total`, `descuento_global_pct`. El cierre trae `asesores_cerrados`, `asesores_total`; `estado` es `cerrado` solo si todos los asesores lo están; `resumen` agrega `ventas_periodo` y `descuento_global_pct`. `POST …/cierres/{id}/reabrir/` ya no exige `motivo`; editar líneas/ajustes/asesor de una fila cerrada → 409; borrar un cierre con algún asesor cerrado → 409.
