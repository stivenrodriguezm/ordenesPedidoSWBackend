# Matriz de permisos (estado tras P02, 2026-10-02)

Fuente única: `ordenes/permissions.py` → `permisos_efectivos(user)` (la usan la API y `GET /api/user/`). El rol **administrador** tiene todo (`ALL`). Un rol **sin fila** de configuración usa sus valores por defecto (solo auxiliar tiene; el resto, ninguno); una **lista vacía** significa sin permisos. La migración `ordenes 0037` crea la fila de cada rol con exactamente sus permisos efectivos previos. `GET /api/role-permissions/` ya no escribe.

## Equivalencias (código que exige el backend ← códigos que lo satisfacen)

| Exige | Lo satisface |
|---|---|
| VER_VENTAS | VER_VENTAS, VER_TODAS_VENTAS, VER_PROPIAS_VENTAS |
| VER_CAJA | VER_CAJA, ACCESO_CAJA |
| VER_RECIBOS | VER_RECIBOS, ACCESO_RECIBOS |
| VER_COMPROBANTES_EGRESO | VER_COMPROBANTES_EGRESO, ACCESO_EGRESOS, VER_TODOS_EGRESOS, VER_PROPIOS_EGRESOS |
| CREAR_ITEM_INVENTARIO | CREAR_ITEM_INVENTARIO, CREAR_ENTRADA_MANUAL, CREAR_GRUPO_INVENTARIO, CREAR_FACTURA |
| ADMINISTRAR_REFERENCIAS (referencias, categorías, subcategorías) | ADMINISTRAR_BASES (heredado), ADMINISTRAR_REFERENCIAS |
| ADMINISTRAR_PROVEEDORES | ADMINISTRAR_BASES, ADMINISTRAR_PROVEEDORES |
| ADMINISTRAR_SEDES (sedes, zonas) | ADMINISTRAR_BASES, ADMINISTRAR_SEDES |

Antes, `VER_VENTAS` y `ADMINISTRAR_BASES` no podían marcarse desde la pantalla de permisos: configurar "ver ventas" en la UI no daba acceso real a la API.

## Alcance por objeto

| Objeto | Regla (consulta y escritura usan la misma función) |
|---|---|
| Venta (`ventas_visibles`) | administrador o VER_TODAS_VENTAS → todas; rol vendedor, o quien tiene solo VER_PROPIAS_VENTAS → propias/compartidas; otros roles → todas (alcance previo conservado). Aplica a listado, detalle, edición, observaciones, remisiones heredadas y creación de recibos |
| Orden (`ordenes_visibles`) | VER_TODAS_ORDENES → todas; rol vendedor o solo VER_PROPIAS_ORDENES → propias/de sus ventas; otros → todas. Aplica a listado, `/completo/`, `/pedidos/<id>/detalles/`, detalles directos. El ViewSet conserva su regla previa (sin TODAS/PROPIAS → ninguna) |
| Remisión | ítems de inventario: deben ser de una venta de la remisión o stock libre en exhibición/consignación (H14) |

## Acciones y campos

| Acción | Permiso | Campos / notas |
|---|---|---|
| Editar venta (cabecera completa) | EDITAR_VENTA | puede cambiar datos del cliente |
| Cambiar estado de venta / de pedidos | EDITAR_ESTADO_VENTA / EDITAR_ESTADO_PEDIDOS_VENTA | solo esos campos; cambiar el cliente exige además EDITAR_VENTA o EDITAR_CLIENTE |
| Anular venta | ANULAR_ORDEN_PEDIDO | — |
| Ver costo de órdenes | VER_COSTOS_ORDEN | el campo `costo` se elimina del cuerpo (listado, detalle, completo, detalle de venta) |
| Ver costos de inventario | VER_COSTOS_INVENTARIO | se eliminan `costo_especifico`, `costo_total`, `tela_costo_metro`, `costos_adicionales`, costos de telas; y `costo_total` de grupos. Sin el permiso, los costos enviados al editar se ignoran |
| Movimiento manual de caja | CREAR_INGRESO_CAJA / CREAR_EGRESO_CAJA | solo `ingreso`/`egreso`, importe > 0 |
| Cierre de caja | VER_CAJA + **CERRAR_CAJA** | Deja constancia sin cambiar el saldo (Turnos de caja eliminado, D-ALCANCE) |
| Editar egreso | EDITAR_COMPROBANTE_EGRESO | cambiar `estado` (confirmar/revertir) exige además **APROBAR_EGRESO** |
| Confirmar egreso | APROBAR_EGRESO | registra `aprobado_por` y `fecha_aprobacion` |
| Lista de precios: leer | VER_LISTA_PRECIOS / VER_COSTOS_LISTA_PRECIOS | solo acciones `list`, `retrieve`, `impacto` |
| Lista de precios: cualquier otra acción (incluida `asignar-multiplicador`) | EDITAR_LISTA_PRECIOS | denegación por defecto (H08) |
| Consultar comisiones y liquidaciones | **VER_COMISIONES** | Vendedor ve solo sus propias liquidaciones; administrador o usuarios con VER_TODAS_VENTAS ven todas |
| Administrar reglas y cerrar períodos de comisiones | **GESTIONAR_COMISIONES** | Crear reglas, recalcular, registrar ajustes compensatorios y cerrar/congelar períodos |
| Usuarios: crear/editar/desactivar | ADMINISTRAR_USUARIOS | sin ser administrador: no asigna ni quita el rol administrador, no modifica administradores, no cambia su propio rol (D01 provisional). Último administrador activo protegido. DELETE = desactivar |
| Matriz de roles | solo rol administrador | GET sin efectos; no se crean ni borran roles |

## Inventario (P11-02, 2026-10-06)

| Acción | Permiso | Notas |
|---|---|---|
| Ver historial de una unidad | VER_INVENTARIO | — |
| Devolver una unidad al proveedor | EDITAR_ITEM_INVENTARIO | motivo obligatorio |
| Confirmar entrega con productos no entregados | transportador asignado o CAMBIAR_ESTADO_REMISION | P11-03 |

## Nómina (D12a, 2026-10-06)

| Acción | Permiso | Notas |
|---|---|---|
| Ver cierres, configuración y básicos | VER_NOMINA | muestra salarios: no se asigna por defecto |
| Crear, recalcular, editar, cerrar, reabrir y configurar | GESTIONAR_NOMINA | — |

## Pendiente

- `VER_PRECIOS_VENTA` existe en la UI pero el API no oculta importes de venta (no estaba en el informe; decidir si aplica).
- MFA y separación preparador/aprobador (D01/D07).

## Calidad de clientes (P13-03, 2026-10-06)

| Acción | Permisos acumulativos | Alcance |
|---|---|---|
| Listar fichas, candidatos, comparar, consultar vista previa e historial | VER_CLIENTES + **VER_CALIDAD_CLIENTES** | Administrador/global según `ve_todas_las_ventas`; vendedor limitado solo clientes de ventas propias/compartidas, sin exponer candidatos ajenos |
| Aplicar formato seleccionado | Los anteriores + EDITAR_CLIENTE + **NORMALIZAR_CLIENTES** | Misma selección de clientes y comprobación de versión; también revalida alcance al repetir una clave idempotente |

Los dos permisos nuevos aparecen en Usuarios → Clientes y no se conceden a roles por defecto ni mediante migración. Menú y ruta requieren ambos permisos de lectura; las casillas y el botón de guardar requieren los dos de escritura. La API valida independientemente cada permiso. El historial contiene datos personales anteriores; no hay API para borrarlo, editarlo, exportarlo o fusionar clientes. Estas garantías pertenecen al módulo nuevo: revisar rutas heredadas y exportaciones como parte de P13-04.

## Acceso y exportaciones revisadas (P13-04, 2026-10-06)

| Acción | Permiso / alcance | Campos y límites |
|---|---|---|
| Directorio y detalle básico de clientes | `VER_CLIENTES`, global como antes; D06d provisional | Datos básicos de ficha; buscar documento no autoriza ventas ajenas. Edición existente pendiente de política de negocio y revisión de todas sus rutas |
| Historial de ventas por cliente | `VER_CLIENTES` + permiso de ventas; `ventas_visibles` | Solo ventas autorizadas, incluso si el mismo cliente tiene otras; conserva protección de márgenes |
| Leer/añadir notas del cliente | `VER_CLIENTES`; `clientes_visibles` | Notas compartidas de cliente visible; no notas de clientes ajenos. Añadir registra autor de sesión |
| Editar/borrar nota | Lo anterior y autor/`EDITAR_CLIENTE` según regla existente | Ser autor no elude pérdida de alcance del cliente |
| Exportar clientes | `VER_CLIENTES` + `EXPORTAR_CLIENTES`; `clientes_visibles` | Nueve campos básicos, sin importes/historia/notas. Global incluye clientes sin ventas; vendedor limitado solo clientes de ventas propias/compartidas. Máximo 10 000 |
| `PUT/PATCH` de período de comisión | `GESTIONAR_COMISIONES` y período abierto | No acepta editar un período cerrado ni mutarlo con solo permiso de lectura |

No se crearon permisos ni se concedieron nuevos accesos. `ve_todas_las_ventas` conserva su semántica: administrador/`VER_TODAS_VENTAS` global; vendedor o `VER_PROPIAS_VENTAS` limitado; otros roles conservan su alcance previo. `GESTIONAR_COMISIONES` mantiene alcance global de gestión. D06d no está confirmado por el usuario. Esta matriz no acredita todavía otras exportaciones, impresión ni acceso directo a adjuntos; ver `exportaciones-y-datos.md`.

**2026-10-08 (D18):** `GESTIONAR_PERFILES_IA` — crear, editar, pausar y borrar perfiles de IA y sus documentos (inicialmente solo administradores, que tienen `ALL`). Usar perfiles, valorar respuestas y gestionar lo aprendido propio solo exige `USAR_ASISTENTE_IA`.
