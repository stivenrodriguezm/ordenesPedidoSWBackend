# Especiales y biblioteca común

## Identidad unificada con Referencias (2026-10-16)

En la rama `modificar_lista`, `LineaProducto.referencia` es un vínculo único a `ordenes.Referencia`: la lista configura precios de la referencia existente. La pantalla y API de Referencias no se modifican. Nombre y proveedor se leen siempre de esa relación; no se crean referencias desde precios ni se reasigna una lista a otro ID. Las referencias homónimas de distintos proveedores permanecen separadas. Se usan sus categorías (`categoria_referencia`) y tipos (`subcategoria`) de `suministros`; `VarianteProducto.categoria` y los nombres antiguos se conservan solo para compatibilidad histórica. Sin clasificación se permite capturar medidas sin crear categorías.

`GET referencias/` del módulo de precios presenta configuradas y pendientes, sin recalcular precios. La configuración nueva se crea en borrador, conserva costos/consumos/múltiplos/cargos/especiales/orden y se publica explícitamente. Cada edición refresca solo su referencia. El antiguo editor de categorías independientes deja de aparecer. El indicador comercial `es_decorativo` conserva los cojines incluidos sin depender del slug anterior.

La migración 0021 vincula únicamente nombres normalizados que son únicos en ambos catálogos; archiva las listas ambiguas o sin referencia en vez de asignarlas por aproximación. No cambia filas de Referencias, proveedores ni sus clasificaciones. La 0022 conserva el indicador de decorativos. Cotizaciones y ventas históricas mantienen sus importes; los productos nuevos llevan el ID exacto al flujo existente de ventas/pedidos y se rechaza un proveedor/referencia distinto. La importación anterior solo admite referencias inequívocas y deja lo importado en borrador. Pruebas: `test_referencias_unificadas.py`, `test_crear_linea.py`, cotizaciones y productos de venta.

Se aplicaron exclusivamente 0021/0022 en la base de pruebas `u756180748_pruebasv3`, con respaldos locales de precios en `/private/tmp/lottus-respaldo-unificacion-20261016-105635` (antes de unificar) y `/private/tmp/lottus-respaldo-unificacion-20261016-110246` (antes del indicador), y comprobación de identidad de Referencias antes/después. `Prototipo` sigue conservando los commits anteriores de código; una reversión de datos requiere esos respaldos, no cambiar solamente de rama. No ejecutar migraciones generales para esta entrega.

Regla del usuario (2026-10-15): los especiales se tratan casi como productos. Se captura **costo**, un **multiplicador propio** (o el general), sentido **sube/baja** y consumos independientes de tela y cuero. Todos los importes visibles y editables son COP sin decimales (`$3.000.000`). No usar el precio de venta como si fuera el costo.

La diferencia de venta es `(costo + consumo del material × precio del grupo) × multiplicador del especial`, con el signo elegido. Se suma al precio del producto **después** del multiplicador del producto, incluso si tiene precio manual o es un conjunto. El costo interno sí incluye el costo firmado y el material del especial. Nunca aplicar dos veces el margen. Un especial con material solo se puede cotizar en grupos cuyo consumo esté configurado; tela usa metros y cuero decímetros, sin conversiones automáticas.

`EspecialLinea.configuracion` guarda los parámetros generales y `CargoVariante.configuracion_especial` las excepciones por producto. El tipo `especial_producto` usa esa fórmula. Las excepciones siguen editables y se pueden restablecer a la configuración general. Se exige al menos un producto, importes enteros, consumos y múltiplos válidos, y precios finales no negativos. Las escrituras de especial, aplicaciones y biblioteca son atómicas.

`EspecialCatalogo` es la biblioteca común persistente: reúne todos los nombres y configuraciones, incluidos costos distintos del mismo nombre. Al guardar se archivan automáticamente los parámetros, sin duplicar una configuración idéntica. Reutilizar copia sus datos a la colección elegida; editar o quitar esa copia no modifica las demás ni borra la biblioteca. La migración 0017 agrega la biblioteca y dos campos JSON, copia los especiales anteriores sin cambiar sus precios.

Los contratos históricos (`valor` como costo con multiplicador del producto y `diferencia_precio` como ajuste de venta fijo) se conservan para los datos existentes. Abrir o renombrar no convierte ni redondea esos datos. La administración muestra su costo y multiplicador equivalentes y solo pasa al nuevo formato cuando se confirman cambios de configuración. Sus creaciones y renombrados también alimentan la biblioteca.

El guardado del editor lee y valida el borrador actual al enviar el formulario; no debe depender de una petición o de confirmar cada campo al salir con `blur`. Conservar todo lo escrito si falla el servidor y actualizar la caché con la respuesta confirmada, además de invalidar el catálogo del vendedor y la biblioteca.

**Comparar se retiró por decisión del usuario.** No volver a agregar comparación, comparador ni botones de comparación en la lista de precios. El flujo es consultar, configurar y agregar a la cotización.

Pruebas: `test_especiales_configurables.py`, `test_diferencias_especiales.py` y los tests de React de `JuegosEspeciales` / `ListaPreciosPage`. Reglas generales de moneda: `../../AGENTS.md` de la raíz del espacio de trabajo.

## Rendimiento de administración (2026-10-16)

`GET lineas/?resumen=1` devuelve únicamente cabeceras e identidad/categoría/orden de las variantes, sin ejecutar el motor de precios. Al expandir se pide `GET lineas/{id}/`, que conserva el contrato completo. Ambos exigen el permiso habitual de ver costos. El frontend mantiene cada detalle en caché y refresca solo la colección afectada al editar; también sus conjuntos dependientes y el catálogo del vendedor. Las actualizaciones globales siguen invalidando todas las colecciones.

Los cálculos deben usar relaciones precargadas, incluidas las listas vacías de componentes de las piezas individuales: consultar esa relación dentro de cada cálculo disparaba consultas repetidas por grupo. Después de un PATCH se vuelve a precargar la variante una sola vez para representar sus precios. No sustituir los cálculos por valores aproximados ni perder borradores al actualizar el servidor. `test_rendimiento_admin.py` limita las consultas SQL y comprueba que añadir productos no las multiplica.

## Orden de variantes y agrupaciones

El administrador ordena variantes por arrastre. `orden-variantes` guarda **la lista completa de IDs de la colección** en una transacción y exige el orden anterior: si otra sesión cambió el orden o las piezas, devuelve 409 sin escribir parcialmente. El catálogo y su selección inicial respetan ese orden; los nuevos productos y agrupaciones se añaden al final. Las actualizaciones masivas invalidan la caché del vendedor.

Una agrupación es una variante con `ComponenteJuego`: pieza, cantidad entera de 1 a 99 y, opcionalmente, `costo_unitario` y `multiplicador`. Estos dos valores son exclusivos de la agrupación. **Nulo hereda del producto; cero es un costo explícito.** No escribir ajustes del conjunto sobre los costos de las variantes originales. No se admiten piezas duplicadas, ajenas a la colección, conjuntos anidados ni ciclos.

Cada pieza se calcula como `(costo base unitario propio o heredado + consumo del material × precio del grupo + cargos fijos) × multiplicador propio o heredado`, por su cantidad. Si no hay ajustes, se conserva también su precio manual histórico; al poner costo o múltiplo propios se usa la fórmula solo en esa agrupación. Los consumos de tela y cuero siguen siendo los de la pieza. El costo interno de cotizaciones/ventas usa también el costo exclusivo, sin confundirlo con venta.

El total del conjunto suma las ventas de las piezas y añade **solo sus costos adicionales y cargos propios** con el multiplicador del conjunto. Nunca multiplicar otra vez las ventas de sus piezas. Un precio manual del conjunto sigue prevaleciendo hasta que el administrador lo retire explícitamente. Los especiales siguen sumándose después, con su propia fórmula.

Crear una agrupación guarda variante y piezas en una sola transacción. Editar exige una lista explícita de componentes (`[]` convierte en producto individual; omitir el campo no borra nada). La simulación es de solo lectura y calcula con el mismo motor que el guardado. Se valida el cálculo antes de escribir y se conservan los borradores del frontend ante errores. La migración 0018 solo agrega dos columnas nulas: no recalcula ni reescribe precios anteriores. Regresiones: `test_agrupaciones_orden.py`, `AgrupacionVariante.test.jsx`, `VariantesOrdenables.test.jsx`.

### Total y adicionales por pieza (2026-10-15)

La cabecera administrativa muestra **Costo total del producto**, de solo lectura, obtenido de `costo_lista(..., sin_material=True)`: costos base por cantidad, cargos fijos heredados, adicionales por pieza y costos propios de la agrupación. La base excluye tela/cuero porque depende del grupo elegido; la simulación devuelve también `costos_por_grupo` con el material incluido. No confundir este total con `VarianteProducto.costo_base`, que conserva los otros costos propios, editables en el detalle. No introducir multiplicadores de venta en los costos.

`ComponenteJuego.adicionales` contiene copias independientes de cargos (`tipo`, `nombre`, `costo`) y especiales (`tipo`, `nombre`, `configuracion`). Se aplican por cada unidad de la pieza: el cargo usa el múltiplo efectivo de esa pieza; el especial, su propio múltiplo o el general. Los especiales pueden subir/bajar y consumir tela y cuero por separado. Se filtran los grupos incompatibles y se impiden precios de pieza negativos. Los cargos fijos originales se incluyen una sola vez. Guardar estos adicionales no modifica cargos, especiales ni costos de las variantes originales.

Los especiales de las piezas se archivan en la biblioteca común únicamente al confirmar la transacción; simular no escribe ni archiva. Sus nombres aparecen en el resumen público del conjunto, sin costos ni márgenes internos. Omitir `adicionales` conserva lo guardado para clientes anteriores; enviar `[]` los retira explícitamente. La migración 0019 agrega solo el campo JSON con lista vacía, sin cambiar configuraciones anteriores.

## Subcategorías como productos y agrupación visual (2026-10-16)

En una lista vinculada a Referencias, `VarianteProducto` es únicamente la ficha comercial de una subcategoría asignada. Se conserva el nombre técnico de tabla/API para documentos históricos y el motor de cálculo. La identidad es `(linea, subcategoria)` con restricción única; nombre y categoría visibles se leen del maestro. No se permiten nombres/medidas libres ni reasignar una ficha a otra subcategoría. No modificar datos maestros desde precios.

Configurar una referencia crea todas sus fichas de costos en borrador. `costo_confirmado=False` diferencia un cero inicial de un costo cero confirmado explícitamente. Publicar exige correspondencia completa con las subcategorías asignadas y costos confirmados para todas. `sincronizar-subcategorias` agrega los tipos nuevos sin duplicar ni sobrescribir costos y vuelve a borrador si incorpora fichas. GET nunca escribe. Las referencias sin subcategorías indican que deben asignarse en Referencias.

Formar un conjunto configura los componentes de una ficha existente, elegida por subcategoría; no agrega otra variante paralela. Conserva los costos y múltiplos exclusivos de sus piezas y los adicionales existentes. Al volver a producto individual hay que confirmar su costo propio.

La migración 0023 conserva como archivo inactivo cualquier colección con productos sin correspondencia exacta o repetidos, preservando IDs, costos, precios y `referencia_archivada` para conversiones históricas. Genera una configuración nueva en borrador con las subcategorías reales. No inventa equivalencias por semejanza ni modifica Referencia, Proveedor, categorías o subcategorías. Respaldar precios y comprobar la huella de datos maestros antes/después. En la base compartida aplicar solo el destino 0023 con plan exacto; nunca migraciones generales.

Agrupar por referencia reúne nombres para presentación, manteniendo cada ID/proveedor como configuración separada. Agrupar por proveedor usa el ID del proveedor. Buscar filtra referencias antes de agrupar, incluyendo subcategorías aunque no tengan precios. No sumar, copiar ni compartir costos por coincidencia de nombre. Cambiar grupo, filtros o búsqueda debe proteger entradas pendientes; las cabeceras no calculan ni cargan detalles de precios.
