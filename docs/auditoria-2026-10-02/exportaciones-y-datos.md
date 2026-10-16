# P13-04: exportaciones y acceso a datos

Estado al 2026-10-06: entrega parcial validada localmente, sin despliegue. Se revisaron código y pruebas con datos ficticios; no se inspeccionaron SIIGO ni datos operativos. Decisiones D06d/D06e en [decisiones.md](decisiones.md); evidencia en [validacion.md](validacion.md).

## Comportamiento implementado

| Superficie | Control y contenido | Evidencia / límite |
|---|---|---|
| Directorio básico `GET /api/clientes/` y detalle | Conserva lectura global con `VER_CLIENTES`; filtros compartidos con exportación y respuesta `no-store`. Informa permiso/alcance de exportación | D06d provisional; consulta global no concede acceso a ventas ajenas. La edición vigente se conserva, no se declara revisada en todas las rutas |
| Historial de cliente y notas | `clientes_visibles` centralizado; ventas con permiso de ventas y alcance propio/compartido; notas solo de clientes visibles. Añadir/editar/borrar una nota exige cliente en alcance, además de las reglas de autor/edición existentes | Cliente visible puede tener ventas de otros vendedores: esas ventas quedan fuera de la respuesta. Notas del cliente se comparten entre usuarios con acceso a ese cliente; no se filtran por autor para leer |
| XLSX de clientes | `POST /api/clientes/exportar/`, `VER_CLIENTES` + `EXPORTAR_CLIENTES`; filtro completo dentro de clientes visibles, hasta 10 000. Columnas: ID, nombre, documento, correo, dirección, barrio, ciudad y dos teléfonos; sin notas, ventas, costos ni historia | Auditoría `clientes.exportar`; archivo construido en memoria. Todas las celdas de datos son texto explícito; conserva ceros y prefijo telefónico. Caracteres XML inválidos provocan 400 sin cambiar originales. Sobre límite: 413, nunca archivo parcial |
| Comisiones: períodos, reglas y liquidaciones | Lectura con `VER_COMISIONES`; global con `GESTIONAR_COMISIONES` o alcance global vigente, resto propio. Totales/conteos y tasas específicas respetan ese alcance. Edición genérica de período exige gestionar y rechaza cerrado | No modifica el cálculo de comisiones ni sustituye una revisión de concurrencia de cierre/recalcular. Metadatos comunes de períodos/reglas siguen consultables con el permiso de lectura |
| CSV de comisiones | Mismo alcance que liquidaciones; todo el período autorizado, UTF-8 BOM y separador `;`. Hasta 10 000 renglones de detalle + resumen por liquidación, sin contar encabezados/separadores. No aplica filtro visual por nombre | Auditoría `comisiones.exportar`. Texto que comienza como fórmula, incluso tras blancos/caracteres invisibles, se prefija con apóstrofo. Números `Decimal`, incluidos ajustes negativos, conservan su valor |
| CSV de conciliación | Mantiene permisos por cruce, filtro, auditoría y límite existentes. Reutiliza la protección de texto común mejorada | No se declara implementada ninguna conciliación adicional en esta entrega |

Auditoría significa **archivo generado por el servidor**, no prueba de recepción/lectura. Se registra usuario, acción, fecha, formato, alcance y conteos; clientes añade columnas y huellas HMAC de filtros aprobados. No se copian nombres, contactos, documentos ni texto de búsquedas a esos eventos. La tabla de auditoría y el acceso a los propios archivos siguen sujetos a D06b. Cada solicitud exitosa genera un evento; no hay idempotencia de descargas. Un fallo al escribir la auditoría impide entregar el archivo. Los archivos nuevos responden `Cache-Control: no-store` y `X-Content-Type-Options: nosniff`.

La UI explica alcance y filtros, bloquea doble clic mientras genera y muestra errores recuperables. Clientes espera a que el filtro escrito coincida con el filtro aplicado y comprueba permiso de sesión y respuesta de servidor. El servidor siempre vuelve a autorizar. Una descarga con cero coincidencias genera un archivo de encabezados dentro del permiso existente.

## Inventario pendiente para continuar

Las rutas siguientes son puntos de entrada verificados en el código, **no una afirmación de vulnerabilidad confirmada**. Su existencia no queda cubierta por las pruebas de clientes/comisiones.

| Superficie pendiente | Punto de entrada | Próxima comprobación |
|---|---|---|
| Ventas | Frontend `src/pages/Ventas.jsx`, generación XLSX | Contrato de filtro/paginación, alcance y campos/precios/márgenes en todas las rutas; trasladar o complementar con generación autorizada y auditoría en servidor |
| Recibos de caja | Frontend `src/pages/RecibosCaja.jsx`, generación XLSX | Alcance de venta, confirmaciones, filtrado completo, auditoría y texto literal sin alterar importes |
| Comprobantes de egreso | Frontend `src/pages/ComprobantesEgreso.jsx`, generación XLSX | Permisos de exportación, datos del proveedor, filtros/estados y trazabilidad. Preservar la diferencia entre PDF «Pagado» y estado real de transferencia |
| Inventario | Frontend `src/pages/InventarioPage.jsx`, generación XLSX | Permisos de costos/campos, límites, filtros y trazabilidad. No cambiar identidad, reservas ni cantidades al exportar |
| Evidencias de posventa | Backend `ordenes/posventa_serializers.py` (`archivo`, `archivo_url`) y `ordenes/posventa_views.py` (`descargar_evidencia`) | Comprobar permisos del caso, URL devuelto y acceso directo al almacenamiento; probar usuario ajeno, permiso revocado y archivo ausente. No basta proteger la vista si el recurso directo permite otra ruta |
| Otras impresiones/adjuntos | Inventariar generadores PDF, impresión de documentos y archivos desde rutas/serializers | Comparar alcance, campos y caché con API de origen; conservar identidad/documento histórico, nunca deducir seguridad por ocultar botón |
| Directorio y edición | Backend `ordenes/views.py`: listar/obtener cliente y alta/edición mediante ventas; módulos que reciben cliente anidado | Resolver D06d y recorrer todas las escrituras según decisión; no imponer silenciosamente propiedad exclusiva de ficha al vendedor |

Para cada salida: fijar campos y permisos por rol, escribir pruebas negativas de API/archivo, compartir el filtro autorizado, rechazar volúmenes excesivos sin truncar, registrar generación sin copiar PII y verificar los errores en UI. Conservar filtros/semántica comercial existentes; no mover cálculos personales Total/N a documentos que muestran el 100 %. No añadir exportación a SIIGO (D06a).

## Trabajo que permanece abierto

- Fusión de P13-03: inventariar referencias e identidad histórica antes de trasladar documentos; comparación actual no fusiona ni borra.
- D06b: responsable, plazos/causales, solicitudes y excepciones documentales; no hay eliminación/anonimización automática ni afirmación de cumplimiento legal.
- D06d: pregunta de alcance del directorio/edición todavía sin respuesta. Implementación provisional preserva la lectura básica global y limita historia/exportación comercial.
- P14: recorrer descargas con roles reales en staging, escritorio y móvil; verificar Excel/lector CSV, controles de almacenamiento y aceptación con operadores. Las pruebas jsdom y lectura programática del XLSX no sustituyen esos recorridos.

No hay nuevas dependencias ni migraciones en este avance. La migración 0047 de calidad de clientes continúa preparada, sin aplicarse aquí a ninguna base persistente. Actualizar **siempre `planMejora.md`**, su resumen y sus casillas al continuar; estos anexos no reemplazan ese paso.
