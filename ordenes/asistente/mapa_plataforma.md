# Mapa de la plataforma (frontend + backend)

Guía para entender cómo habla el usuario de la plataforma y responder en su lenguaje.
La reciben **todos** los perfiles. Si cambia una pantalla, un menú o un estado,
actualízala aquí. El esquema de la base de datos se agrega automáticamente
(`asistente/esquema.py`), así que aquí no se repiten los campos.

## Cómo usar este mapa

- El usuario habla con nombres de pantallas, botones, columnas y siglas («la OP», «el
  RC», «la gestión atrasada», «el cierre de agosto»). Tradúcelos al concepto y a los
  datos con este mapa y el glosario, y luego consulta con las herramientas.
- Si pregunta **cómo hacer algo** en la plataforma, responde con la ruta exacta del menú
  y los pasos (p. ej. «Menú → Ventas → expande la venta → Productos → Finalizar
  gestión»). Si pide hacerlo, encárgaselo a Alan (agente ejecutor) y comprueba el resultado.
- Si pregunta **por qué ve algo** (un total en cero, una venta que no aparece, un
  estado), explica la regla que lo produce (sección «Reglas que suelen confundir») y, si
  hay datos, compruébalo con las herramientas antes de concluir.
- Si algo no está en este mapa ni en los datos, dilo; no inventes pantallas ni botones.
- **Dinero siempre en pesos colombianos sin decimales**, con `$` y puntos de miles:
  `$3.000.000`. Los valores del sistema que llegan como `3000000.00` son tres millones (nunca
  trescientos millones). Solo porcentajes y consumos (metros de tela, decímetros de cuero)
  pueden llevar decimales, y se escriben con coma: `11,5 dm`, `25 %`.
- Cada opción del menú exige un permiso; si el usuario no ve algo, puede ser falta de
  permiso (se asigna en Gestión de usuarios, `/gestion-usuarios`, solo administradores).

## Menú lateral (sidebar) y pantallas

### General
- **Inicio** (`/`): para el administrador es el **Panel general**: ventas del período comercial
  frente al mismo día del período anterior (variación, proyección al cierre, ticket), ventas de
  hoy, recaudo confirmado, caja y saldo por cobrar (ventas de los últimos 90 días); gráfico de
  ritmo acumulado (o comparación anual), ranking de asesores (compartidas Total / N) y ventas por
  sede; **Requiere tu atención** (gestión atrasada, entregas vencidas, OP atrasadas, telas por
  pedir, remisiones atrasadas / de hoy / sin transportador, pagos y egresos por confirmar,
  facturas vencidas o que vencen en 7 días, nómina por cerrar), cada uno con enlace a su módulo;
  caja para preguntarle a IA Lottus, agentes e informes automáticos; últimas ventas. Los
  vendedores ven su tablero personal.
- **Ventas** (`/ventas`): listado de ventas del período (filtros por fecha, vendedor,
  sede, búsqueda por OC o cliente; exportar a Excel). La tabla carga de a 100 ventas y
  abajo está **Ver más ventas**. El filtro de vendedor incluye a todos los que vendieron
  en el período (también inactivos); al cambiar de mes vuelve a «Todos». Al filtrar por
  vendedores, el total y las Estadísticas suman solo su parte de las ventas compartidas
  (1.000.000 entre dos → 500.000 a cada uno); sin filtro, cada venta cuenta completa. Columnas: venta/OC, cliente,
  vendedor, sede, total, abono, saldo, estado y **Gestión** (Pendiente / Atrasada /
  Finalizada). **Nueva venta** (`/ventas/nueva`) registra la venta con valor total
  global, cliente, vendedores (puede ser compartida), sede, abono y la marca
  **Postferia** (solo estadística). Al **expandir una venta** se ve el panel
  **Productos**: al editarlos, cada producto es una ficha con su cantidad (− / +), su
  precio de lista y tres secciones con ✓ cuando están listas: **1 Compra** (referencia del
  proveedor), **2 Tela** («¿Lleva tela?» No / Sí, la pone el proveedor / Sí, la compramos
  aparte; solo si lleva: material tela en metros o cuero en decímetros, **grupo** —en un
  producto de catálogo define el precio de lista—, referencia, color, a quién se compra,
  cantidad y, solo si la compramos aparte, **costo del proveedor por m o dm**, por defecto el del grupo) y **3 Textos**
  (para el proveedor o «No aplica», y para el cliente, **opcional**: sin él, la remisión
  usa el nombre del producto). Plegada, la ficha muestra un resumen de esas tres cosas. Se puede guardar la venta sin productos. Fuera de la edición los productos se ven como
  **tarjetas**. **Cojines incluidos**: un producto con el cargo «Decorativos x2» cubre, por
  cada unidad, 2 productos de la línea **Decorativos** sin cobro (en grupo 1 o 2; de grupo 3 en
  adelante se cobra la diferencia frente a su precio en grupo 2). Si llevan más decorativos que
  el cupo, quedan incluidos los de mayor valor cubierto y el resto se cobra. Al guardar, el
  decorativo cubierto dice «Incluido… −$X» y ese valor se resta del precio de lista de la
  venta (lo mismo en la cotización). **Conjuntos** (comedor = mesa +
  sillas, cama = base + cabecero…): las piezas se ven juntas en un solo bloque, con nombre,
  cantidad de conjuntos y grupo de tela para todas, pero cada pieza se pide y se factura
  con su referencia; un juego de la lista de precios se agrega como conjunto. También servicios
  (transporte), artículos adicionales y **ajustes ±**. Desde ahí se **generan los
  pedidos al fabricante** (una imagen por pedido) y los **pedidos de tela**
  (agrupados por mismo proveedor de tela y misma dirección), se vinculan pedidos
  anteriores (al expandir una orden de pedido se ven también sus **pedidos de tela**), se prepara
  la **remisión** y se pulsa **Finalizar gestión** cuando todo
  está pedido. También hay observaciones de la venta y del cliente.
- **Pedidos** (`/ordenes`): órdenes de pedido (**OP**) a fabricantes. Estados: En
  proceso, Recibido, Anulado. Columnas: OP, venta, proveedor, referencia, tela (estado
  de la tela de esa OP), vendedor, costo, observación, fecha esperada. **Nuevo pedido**
  en `/ordenes/nuevo` genera la imagen de la orden para enviar al fabricante. Puede
  marcarse «para exhibición» (sin venta).
- **Telas** (`/telas`): pedidos de tela o cuero (**PT**) a proveedores de telas.
  Estados: Pendiente, En fábrica, En Lottus. Columnas: PT, venta, proveedor, fabricante,
  tela, cantidad, dirección de entrega, usuario. Se gestionan direcciones de entrega y
  proveedores de tela; cada pedido genera su imagen.
- **Remisiones** (`/suministros/remisiones`): documentos de entrega/despacho al
  cliente. Vistas Lista y Calendario; filtros Para hoy, Para mañana, Por despachar, En
  ruta, Atrasadas, Sin transportador, Entregadas, Devueltas y anuladas. **Nueva
  remisión** desde aquí o desde la venta (botón en Ventas: se autocompleta casi todo); cada producto
  puede marcar «¿Lleva tela o cuero?» y su tapizado (material, referencia y color, tomado de
  la venta) sale en la remisión impresa en hoja carta.
- **Inventario** (`/suministros/inventario`): ítems físicos por grupo, con
  disponibilidad (Cliente, Exhibición, Consignación, Por reparar, No a la venta,
  Entregado…), zona/sede, código QR y traslados.

### Finanzas
- **Caja** (`/caja`): movimientos de la caja general (ingresos, egresos, saldo actual,
  acumulado). Los recibos confirmados y los egresos en efectivo se reflejan aquí.
- **Recibos de caja** (`/recibos-caja`): **RC**, pagos de clientes a una venta; un
  recibo puede tener varios pagos (Efectivo, Bancolombia, Davivienda, Bold, Datáfono…).
  Un pago cuenta cuando se **confirma**; los recibos se pueden editar o **anular** (no
  se borran).
- **Comprobantes de egreso** (`/comprobantes-egreso`): **CE**, pagos a proveedores u
  otros gastos (efectivo o transferencia); la transferencia se confirma cuando se hizo.
- **Facturas proveedor** (`/suministros/facturas`): facturas de compra a proveedores.
  Estados: Pendiente/Por pagar, Pago en proceso, Pagado, Atrasado, Anulada. Al registrar
  la mercancía puede entrar al inventario por grupos.
  En **Nueva factura**, al elegir el proveedor aparece «Pedidos de este proveedor que aún
  no llegan»: se marcan y se agregan con referencia, cantidad pendiente, venta, pedido,
  detalle, telas y un **costo sugerido** = precio de lista ÷ multiplicador (≈1,76), sin la
  tela que se compra aparte. Es una sugerencia: se revisa contra lo que cobra el proveedor.
  En inventario y facturas el campo «Variación» ahora se llama **Detalle** (igual que en la
  lista de precios, donde «Variante» pasó a «Detalle»).
- **Nómina** (`/nomina`): cierres de nómina de asesores por período (del 6 al 5).
  **Nuevo cierre** calcula comisiones por venta (porcentaje según el descuento sobre el
  precio de lista; solo se pagan con el abono mínimo y productos/precio de lista
  confirmados), bonificaciones por cumplir la meta (se pagan desde el cierre siguiente
  al entregar), ajustes (+/−) y salario básico (aparte, día de pago configurado).
  El cierre se elige en la lista desplegable «Cierre de nómina». El básico y la meta salen de
  Configuración y se actualizan al recalcular (o al cambiarlos allí) en los asesores abiertos,
  salvo que se hayan cambiado a mano en ese cierre; el Total nómina no suma el básico (se paga
  aparte). Pestañas: Cierre general y una por asesor; en las comisiones de cada asesor, cada venta se
  expande para ver sus productos, precio de lista, precio de venta, cuadres y pagos.
  La nómina se **cierra por asesor** (en su pestaña: «Cerrar nómina de …», queda como
  pagada; «Reabrir» sin justificación). El cierre general aparece **Cerrado** solo cuando
  todos sus asesores están cerrados; si hay uno abierto, **Abierto**. Cierre general:
  Asesor, Ventas, % Dcto. global (ventas frente a la suma de sus precios de lista),
  Comisiones, Bonificaciones, Básico y Total nómina. Acciones: Recalcular abiertos, Borrar
  (si nadie está cerrado), Exportar a Excel e **Imprimir** la liquidación de cada asesor
  en hoja carta (con su firma, nombre y fecha acepta haber recibido el pago). Configuración: tabla de comisiones, abono mínimo, % de bonificación.

### Bases de datos (`/bases-de-datos`)
Pestañas: **Clientes**, **Calidad de clientes** (datos incompletos o duplicados),
**Proveedores** (fabricantes), **Referencias** (catálogo de referencias por proveedor,
categorías y subcategorías) y **Zonas y Sedes**. La gestión de usuarios y permisos está en el menú del usuario (al pie del menú lateral: tarjeta con
sus iniciales y nombre) → Gestión de usuarios (`/gestion-usuarios`); ahí también Mi perfil y Cerrar sesión.
No hay barra superior.

### Productos
- **Gestión web** (`/paginaweb/gestion`): productos del sitio muebleslottus.com con
  descripción corta, larga, características y materiales (con formato); sin precio
  público. También contactos/PQRS y asesores con tarjeta digital.
- **Consultar precios** (`/lista-precios`): lista de precios por línea de producto,
  variante y grupo de tela; permite armar una cotización.
- **Administrar lista** (`/lista-precios/administrar`): secciones Líneas y Detalles,
  Matriz de Grupos (precio por metro/decímetro), Multiplicadores (margen) y Categorías. En cada
  línea hay **variantes especiales** (p. ej. «Reclinables eléctricos»): opciones con valor
  por producto que el vendedor activa al cotizar o vender (aparecen con ★). En **Cargos** de un
  detalle, el botón **«Cojines incluidos»** agrega el cargo «Decorativos x2» con su valor sugerido
  ($114.000: 2 cojines en grupo 2), editable y con estado como los demás cargos; da 2 decorativos
  por unidad cuando es obligatorio o cuando el vendedor lo elige. El botón **«Transporte»** agrega
  el cargo Transporte de $120.000. Las **notas** de cada
  detalle se escriben en «Nueva nota» (Enter guarda) y el vendedor las ve al consultar. La
  sección «Juego» ya no se arma desde aquí (los juegos guardados siguen sumando sus piezas).
  Cada cargo tiene un estado: **Opcional habilitado** (ya va incluido en el costo total y en el
  precio de lista; al cotizar o vender aparece seleccionado y si se quita el precio baja), **Opcional deshabilitado** (se ofrece sin seleccionar) u
  **Obligatorio** (siempre va en el precio). Las **agrupaciones** (conjuntos armados con
  productos de la colección) se ven como una fila por pieza (cantidad, costo y múltiplo propios
  opcionales); los **cargos de cada pieza son los del producto original**: agregarlos o
  cambiarlos desde la agrupación los cambia en la referencia, y sus opcionales también se
  ofrecen en el conjunto. Un conjunto no tiene «Otros costos»: su costo es la suma de sus piezas.
  Un conjunto tampoco tiene proveedor: sus piezas pueden ser subcategorías de distintos
  proveedores de la misma referencia (tapa, base y sillas de proveedores diferentes) y cada
  una se pide a su propio proveedor.
  En «Líneas y Detalles» cada detalle se captura en una fila: costo base en pesos sin
  decimales, **Tela** (¿aplica? → metros) y **Cuero** (¿aplica? → decímetros) por separado,
  **Tope Dcto** en % (vacío = 25 %) y categoría; Tab guarda y pasa al siguiente campo, Enter
  confirma y Esc deshace lo escrito. Tela y cuero no se convierten entre sí.

### IA
- **IA Lottus** (`/IA`): oficina virtual con zonas y personas que representan los perfiles de IA.
  Clic en un agente abre `/IA/agentes/{id}` y solo su historial; `/IA/general` reúne
  todas las conversaciones personales y respuestas activas, con dos pestañas: **Mis chats** y
  **Equipo IA** (conversaciones entre agentes: IA Lottus le encarga los cambios a **Alan**, el
  agente ejecutor, que empieza de inmediato y vuelve a la oficina de IA Lottus a contarle el
  resultado; también consultas entre colegas e informes de área). En la oficina, «Chats del
  equipo» abre esa pestaña. Al terminar cada tarea, Alan e IA Lottus anotan una lección que
  aparece en «Lo aprendido» («Aprendido en equipo») y se puede pausar o borrar. `/IA/configuracion`
  administra perfiles y su ubicación. La antigua `/chat` redirige a la oficina. Perfiles de IA (agentes especializados con
  instrucciones, áreas de datos y documentos) en «Perfiles de IA»; 👍/👎 y «Enseñar»
  entrenan las respuestas; «Lo aprendido» muestra lo que la IA recuerda. Cada agente (y la IA
  general) puede estar visible para todos o solo para algunos roles, con instrucciones de cómo
  responder a cada rol (Gestionar agentes → «Quién lo ve y cómo les responde»); si alguien no ve un
  agente, puede ser que no esté habilitado para su rol. En la oficina, **Bandeja → Mensajes**
  lista cada chat con personas (y el tablón «Todo el equipo»); al abrir uno se ve su historial y se
  sigue escribiendo ahí. Los mensajes nuevos aparecen como un sobre sobre quien escribió y un aviso.
  Los personajes caminan de vez en cuando a la zona social (solo ambientación).

## Glosario (cómo lo dice el usuario → qué es)

- **OC / número de venta / la venta 1234**: la venta (`Venta`), su número es el id.
- **OP / pedido / orden**: orden de pedido a fabricante (`OrdenPedido` y sus detalles).
- **PT / pedido de tela**: `PedidoTela` y `DetallePedidoTela`.
- **RC / recibo**: recibo de caja (`ReciboCaja`) con sus pagos (`PagoReciboCaja`).
- **CE / egreso**: comprobante de egreso (`ComprobanteEgreso`).
- **Remisión**: entrega al cliente (app suministros).
- **Gestión de la venta**: seguimiento de que todo lo vendido esté pedido (productos,
  telas). Pendiente → Atrasada (más de 3 días sin finalizar) → Finalizada
  (`Venta.estado_pedidos` / gestión).
- **Período / mes comercial**: del día 6 al día 5 del mes siguiente.
- **Lista / precio de lista / descuento**: precio de lista de los productos frente al
  valor vendido; el descuento sale de ahí y define el % de comisión.
- **Venta compartida**: varios vendedores; para metas y comisiones se divide Total / N.
- **Sede**: Lottus 1 o Lottus 2. **Exhibición**: mueble en la tienda, no vendido.
- **Feria del Hogar / Postferia**: marcas estadísticas de la venta.
- **Saldo / cartera / por cobrar**: valor total − abonos confirmados.
- **Cierre**: un cierre de nómina (borrador o cerrado).

## Reglas que suelen confundir

- **Nómina vacía o con ceros**: el cierre incluye las ventas no anuladas de su rango; la
  comisión queda pendiente (no suma al total) si el abono es menor al mínimo o si los
  productos/precio de lista no están confirmados en la venta. Los pendientes pasan al
  siguiente cierre al recalcularlo. Las bonificaciones no se pagan en el mismo cierre
  en que se ganan.
- **Un pago no aparece**: los pagos de recibos cuentan al confirmarse; los recibos
  anulados no cuentan.
- **Gestión atrasada**: la venta tiene más de 3 días y aún no se finalizó la gestión
  (faltan pedidos de productos o de tela).
- **Ventas del período**: se cuentan por fecha de venta, sin anuladas; las compartidas
  se reparten Total / N entre asesores.
