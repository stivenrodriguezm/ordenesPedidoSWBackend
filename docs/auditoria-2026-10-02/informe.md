# Auditoría del ERP Lottus Kemi
Fecha: 2 de octubre de 2026 · Alcance: ordenesPedidoSW + ordenesPedidoSWBackend

## Dictamen ejecutivo

El ERP ya cubre buena parte de la operación comercial y logística. Mantendría React y Django y evolucionaría el sistema de forma gradual. La prioridad es corregir integridad financiera, autorización y conservación del historial: se reprodujeron operaciones rechazadas que dejan datos guardados, saldos de caja negativos, cambios de inventario que pierden trazabilidad y accesos superiores a los permisos configurados.

No recomiendo empezar por una reescritura, microservicios ni un rediseño visual general. Primero haría confiables los procesos que manejan dinero y mercancía; después simplificaría la arquitectura y conectaría mejor cotización, venta, compra, recepción y entrega.

Este informe distingue:
- **Reproducido:** comprobado con datos ficticios en SQLite en memoria, usando el código local.
- **Código/documentos:** evidencia concreta en fuentes; sin explotación ni comprobación en producción.
- **Riesgo de concurrencia:** derivado del código o de una intercalación simulada; requiere pruebas con MySQL aislado.
- **Mejora propuesta:** evolución de producto u operación, no afirmación de que exista un incidente.

“Crítico” significa atención inmediata por integridad del negocio o exposición de credenciales; “alto” exige corrección antes de ampliar o desplegar los flujos afectados; “medio” corresponde a robustez, rendimiento y mantenimiento.

## Alcance y comprobaciones

Se leyeron los cinco documentos Markdown de la raíz, las instrucciones locales y las guías internas de ambos proyectos. Se revisaron modelos, permisos, rutas, serializadores, vistas, configuración, frontend, dependencias, pruebas y despliegue. Se incluyeron listaprecios y paginaweb porque están integrados en estos dos proyectos; no se auditaron los proyectos independientes landingLottus ni webLottus.

La fotografía auditada es el código local: backend HEAD `0a482562` (2026-09-30) y frontend HEAD `3a2417e` (2026-08-18), **incluyendo los numerosos cambios locales y archivos todavía no versionados del frontend**. No equivale necesariamente al software desplegado.

| Comprobación | Resultado |
|---|---|
| Compilación Vite del frontend | Correcta; salida generada en carpeta temporal |
| Pruebas existentes de ordenes, suministros y listaprecios | 21/21 correctas; las 21 pertenecen a listaprecios |
| Descubrimiento completo de pruebas Django | 21 correctas y 1 error al importar test_dashboard |
| Coherencia modelos/migraciones | Sin migraciones nuevas detectadas |
| Comprobaciones dirigidas de esta auditoría | 26, incluyendo controles correctos y una intercalación simulada |
| ESLint sobre App.jsx | Archivo ignorado: la configuración solo selecciona TS/TSX |
| Auditoría automática npm de dependencias | No completada: el entorno no resolvió registry.npmjs.org |
| Estado de soporte Django/SheetJS | Contrastado con documentación oficial |

Las comprobaciones dirigidas bloquean conexiones de red y verifican que la base sea SQLite en memoria antes de crear tablas. No se consultaron ni modificaron datos reales, no se inició sesión en producción, no se desplegó nada y no se rotaron credenciales. No se hicieron pruebas de carga sobre MySQL, revisión del VPS, restauración real de backups ni recorrido visual completo en navegador. Los tiempos y configuración efectivos de producción siguen pendientes de comprobar.

Se adjuntan [resultados.json](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/docs/auditoria-2026-10-02/resultados.json) y [reproducciones.py](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/docs/auditoria-2026-10-02/reproducciones.py). Este último es una herramienta diagnóstica, no una suite de regresión: registra el comportamiento actual, incluidos los fallos.

## Lo que conservaría

- Autenticación JWT y acceso autenticado por defecto; validación de contraseñas, limitación de intentos de login, errores internos genéricos y medidas HTTPS en configuración.
- Uso de Decimal en modelos financieros y empleo de transacciones/bloqueos en varios flujos, aunque falta completar su aplicación.
- Motor de precios separado en servicios y 21 pruebas útiles de fórmulas, opcionales y multiplicadores.
- Unicidad de factura por proveedor y número; selección anticipada de relaciones en varios listados.
- Estados y eventos de remisiones, asignación a transportadores y soporte para ventas compartidas.
- División del frontend por rutas, componentes UI comunes, React Query ya incorporado y renovación de tokens centralizada.
- Rechazo correcto de órdenes vacías. La prueba devolvió 400.
- Bloqueo correcto de PUT y DELETE en remisiones. Ambas pruebas devolvieron 405; una sospecha inicial quedó descartada.

## Hallazgos prioritarios

### H01 · Crítico · Credenciales expuestas y reutilizadas
**Evidencia: código/documentos.** Hay contraseñas en documentos de la raíz y en el script de despliegue. Además, la guía de backend **sí está versionada** y contiene una contraseña que coincide con DB_PASSWORD del entorno local. La documentación señala reutilización entre base de datos y accesos al servidor, y una exposición histórica; no se verificó el repositorio remoto ni que haya ocurrido acceso indebido.

**Mejoraría:** rotación coordinada de todos los accesos relacionados, credenciales diferentes por entorno y servicio, llaves SSH, usuario de despliegue con permisos limitados y almacenamiento de secretos fuera del código. Limpiar documentos e historial después de rotar y activar detección de secretos. Que la raíz no tenga Git no protege las copias, sincronizaciones ni documentos interiores versionados.

Referencia: [guía versionada](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/deployment_guide.md:19), [documentación del VPS](/Users/stiven/Desktop/Coding/pruebaLottusKemi/DEPLOY_VPS.md:11), [script de despliegue](/Users/stiven/Desktop/Coding/pruebaLottusKemi/deploy_backend_vps.sh:12). No se reproducen los secretos en este informe.

### H02 · Crítico · Caja admite saldos negativos y un cierre puede fijar el saldo
**Reproducido.** Un ingreso de -100 devuelve 201 y deja saldo -100. Un usuario con únicamente VER_CAJA puede enviar tipo=cierre y valor=900000 a la ruta general y fijar ese saldo, sin permisos de crear ingresos/egresos.

**Mejoraría:** valores positivos para movimientos normales, rechazo de “cierre” en el alta genérica, permiso exclusivo de cierre y restricciones en base de datos. Los ajustes deben tener signo y motivo explícitos y el servidor debe calcular el saldo. Crear un registro estable de caja por sede/turno para sincronizar movimientos, en vez de depender únicamente de la última fila.

Referencia: [cálculo de caja](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/serializers.py:333) y [autorización por tipo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1251).

### H03 · Crítico · Un error puede dejar una operación financiera parcialmente guardada
**Reproducido.** Con caja vacía, crear un egreso en efectivo de 100 devuelve 400, pero conserva el comprobante y deja su factura como pagada, sin movimiento de caja.

La vista guarda primero comprobante y facturas; después falla CajaSerializer. Al capturar la excepción dentro de la transacción exterior y devolver una respuesta normal, esos cambios previos se conservan. Hay patrones similares en edición de egresos y ventas; editar recibos también guarda cabecera antes de validar todas las líneas.

**Mejoraría:** validar todo antes de escribir y ejecutar cada operación de negocio como una sola unidad que se deshaga íntegramente ante error. Capturar errores fuera del bloque transaccional. Añadir pruebas que comparen el estado completo antes y después de cada fallo.

Referencia: [crear egreso](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1423), [captura del error](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1466), [editar egreso](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1586), [editar recibo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1798). El comportamiento de las transacciones está documentado por [Django](https://docs.djangoproject.com/en/4.2/topics/db/transactions/).

### H04 · Crítico · Editar una factura borra identidades e historial de inventario
**Reproducido.** Al editar productos de una factura, se eliminan todos sus ítems salvo los entregados y se crean otros. En la prueba desaparecieron el ítem original, su historial de traslado y su vínculo con una remisión activa.

**Mejoraría:** actualizar por identificador estable; crear únicamente unidades nuevas; registrar devoluciones/anulaciones como movimientos; impedir sustituciones destructivas de mercancía reservada o despachada. Conservar QR, costos adicionales, telas, traslados y documentos asociados. La edición de una descripción o costo no debe cambiar la identidad de la unidad física.

Referencia: [reemplazo destructivo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:632) y [historial dependiente](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/models.py:218).

### H05 · Alto · Permisos por venta y campos editables incompletos
**Reproducido.** Un vendedor obtiene 403 al consultar una venta ajena, pero con EDITAR_ESTADO_VENTA puede modificar su estado mediante la ruta de edición. En esa misma petición pudo cambiar el nombre del cliente, aunque no tenía permiso de editar clientes.

**Mejoraría:** aplicar una misma selección de objetos autorizados en consulta y escritura; validar por separado cabecera de venta, estado, cliente y vendedores. Separar las acciones de cambiar estado y editar datos. Revisar también observaciones, remisiones heredadas, recibos y pedidos vinculados.

Referencia: [edición de venta](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:800) y [protección que sí tiene la consulta](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1060).

### H06 · Alto · Rutas alternativas revelan órdenes ajenas y costos
**Reproducido.** La ruta normal de una orden ajena devolvió 404, pero su variante “completo” devolvió 200 con costo. El inventario entregó costo_especifico a un usuario con VER_INVENTARIO pero sin VER_COSTOS_INVENTARIO.

**Mejoraría:** reutilizar el control de propiedad en todas las rutas y eliminar campos sensibles desde la respuesta del servidor. Ocultar columnas en React no protege el contenido de la API. Separar respuestas comerciales y administrativas, también en exportaciones.

Referencia: [detalle completo de orden](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:628), [inventario con todos los campos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:167) y [columna oculta en frontend](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/pages/OrdenesPage.jsx:728).

### H07 · Alto · Editar egresos permite saltarse la aprobación del pago
**Reproducido.** Un usuario que solo tiene EDITAR_COMPROBANTE_EGRESO pudo cambiar una transferencia de “Por Confirmar Pago” a “Pagado”, sin APROBAR_EGRESO.

**Mejoraría:** convertir confirmar, revertir y editar en acciones con permisos explícitos; impedir que el CRUD de edición cambie directamente el estado financiero. Registrar quién aprobó, cuándo, qué soporte verificó y el motivo de cualquier reversión. Si la empresa requiere separación de funciones, impedir que quien prepara un pago sea su único aprobador.

Referencia: [estado editable](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1532) y [confirmación protegida](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1476).

### H08 · Alto · Consultar costos permite cambiar precios masivamente
**Reproducido.** Con solo VER_COSTOS_LISTA_PRECIOS, la acción asignar-multiplicador devolvió 200 y cambió el multiplicador de una variante.

**Causa:** get_permissions distingue las acciones CRUD, pero la acción personalizada cae en el permiso de lectura.

**Mejoraría:** mapa explícito de permiso por acción, EDITAR_LISTA_PRECIOS para toda modificación y pruebas negativas de cada acción personalizada. Para cambios masivos: vista previa de precios afectados, confirmación del alcance, historial y posibilidad de restaurar la versión anterior.

Referencia: [permisos y acción masiva](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/listaprecios/views.py:196).

### H09 · Alto · Cambiar un pago pendiente a efectivo desincroniza caja y venta
**Reproducido.** Cambié una línea pendiente de Davivienda a Efectivo y después la confirmé. La venta recibió un abono de 50, pero no se creó ningún ingreso en caja.

**Mejoraría:** una función única que confirme pagos y determine su efecto según el medio; cambios de medio con validaciones y contabilización coherente. Toda línea confirmada en efectivo debe tener exactamente un movimiento asociado, salvo su reversión documentada.

Referencia: [cambio de medio pendiente](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1837) y [confirmación sin movimiento de efectivo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:2098).

### H10 · Alto · Egresos confían en facturas e importes enviados por el navegador
**Reproducido.** Un comprobante del proveedor A por 1 pudo vincular una factura del proveedor B por 900 y llevarla a pago_en_proceso.

**Mejoraría:** validar existencia de todas las facturas, proveedor, estado elegible, saldo pendiente y ausencia de otra aplicación incompatible; bloquear esas filas durante la operación. Calcular en servidor el importe a partir de aplicaciones, descuentos y conceptos estructurados. Si se admiten anticipos, retenciones o pagos parciales, modelarlos expresamente y probar sus ecuaciones.

Referencia: [vinculación masiva sin esas comprobaciones](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1378). El flujo de edición ya tiene algunas validaciones que faltan al crear.

### H11 · Alto · Una factura puede crearse con productos inválidos y sin cuadrar su total
**Reproducido.** El alta de una factura de 999 con una referencia inexistente devolvió 201 y quedó sin ítems de inventario. El helper descarta la referencia silenciosamente y convierte ciertos errores en valores por defecto.

**Mejoraría:** serializadores tipados para cada producto, referencia existente y del proveedor correcto, cantidades válidas, relación categoría/subcategoría y suma de productos/descuentos/cargos reconciliada en servidor. Un dato inválido debe detener toda la factura, con un error preciso en su fila.

Referencia: [entrada como diccionarios genéricos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:574), [referencia descartada](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:464) y [validación de factura](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:599).

### H12 · Alto · Borrado físico y cascadas amenazan documentos históricos
**Reproducido en factura pagada; resto por código.** Se pudo borrar con DELETE una factura vinculada y pagada, aunque su edición está bloqueada. Además, varias relaciones de ventas, usuarios, proveedores y recibos utilizan CASCADE.

**Mejoraría:** desactivar usuarios/proveedores; proteger documentos usados con PROTECT o relaciones históricas preservadas; eliminar DELETE en documentos contabilizados; usar anulación con motivo y reversión. No aplicar borrado lógico indiscriminado: definir reglas por entidad y conservar las referencias financieras.

Referencia: [DELETE usa permiso de editar factura](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/views.py:200), [cascadas de ventas y órdenes](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/models.py:62) y [recibos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/models.py:141).

### H13 · Alto · Estadísticas incorrectas para ventas compartidas y anuladas
**Reproducido.** Para una venta de 300 con tres vendedores, el dashboard de un compartido mostró 150 en lugar de 100. Tras añadir una venta anulada de 600, mostró 750. El conteo de participantes se hace sobre una relación ya filtrada y la exclusión busca “anulado”, mientras Venta usa “anulada”. El gráfico también usa ese estado incorrecto.

**Mejoraría:** cálculo único de participantes antes del filtro personal, constantes de estados y reglas de redondeo documentadas. Impedir que el vendedor principal se repita entre compartidos. Probar principal, compartidos, 1/2/3 o más personas, anulaciones y cierre de período. Conservar el 100% en listados y dividir solo métricas personales, tal como exige el negocio.

Referencia: [dashboard](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:93), [gráfico](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:176) y [estados reales](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/models.py:63).

### H14 · Alto · Una remisión puede reservar mercancía de otra venta
**Reproducido.** Un vendedor creó una remisión para su propia venta e incluyó un ítem perteneciente a otra venta de otro vendedor. La API aceptó y puso ese ítem por_despachar.

**Mejoraría:** validar que cada ítem pertenezca a las ventas autorizadas de esa remisión, o sea inventario disponible cuya asignación esté autorizada. La relación entre venta, producto físico y entrega debe ser una regla del servidor.

Referencia: [validación de ventas e inventario](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:804).

### H15 · Alto · Concurrencia e idempotencia insuficientes
**Código e intercalación simulada.** Dos serializadores de remisión validados antes de guardar pudieron reservar el mismo ítem en dos remisiones. Esto demuestra una ventana entre comprobar y escribir, no una prueba de carga MySQL.

Confirmar un pago lee el estado sin bloquear la fila; dos solicitudes simultáneas pueden pasar la comprobación y aplicar el abono dos veces. El consecutivo de egresos usa MAX(id)+1: el código instalado de Django elimina select_for_update al construir la agregación, por lo que esa expresión no ofrece el bloqueo prometido por su comentario.

**Mejoraría:** transacciones completas con bloqueos sobre entidades estables, orden de bloqueo consistente, transición condicional de pendiente a confirmado, restricciones de unicidad e identificadores de idempotencia. Usar una secuencia/contador bloqueado para números documentales. Validar con solicitudes realmente simultáneas sobre MySQL aislado, incluyendo caja inicialmente vacía.

Referencia: [confirmar pago](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:2081), [consecutivo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1400), [validar reserva](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:826) y [guardar reserva](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:882).

### H16 · Alto · Desactivar DEBUG selecciona la base de producción
**Código.** Cuando hay DB_HOST y DEBUG=False, settings sustituye DB_NAME y DB_USER por los de producción. Preparar un staging con depuración desactivada puede dirigir operaciones a la base real si sus credenciales lo permiten. Además, load_dotenv con override=True prevalece sobre variables del proceso.

**Mejoraría:** separar desarrollo, pruebas, staging y producción explícitamente; respetar siempre la configuración de conexión; cuentas distintas sin acceso cruzado; fallar al arrancar ante combinaciones ambiguas. DEBUG debe controlar la depuración, no elegir una base. Probar esta matriz sin abrir conexiones.

Referencia: [carga del entorno](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/lottusPedidos/settings.py:5) y [selección de base](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/lottusPedidos/settings.py:209).

### H17 · Alto · HTML sin escapar al imprimir etiquetas QR
**Código; no se ejecutó una carga en navegador.** handlePrintQR interpola nombre de producto e identificador dentro de document.write. Esos datos son editables y no atraviesan el escape de React en ese punto, creando una vía de inyección HTML/JavaScript al imprimir. El almacenamiento de tokens en localStorage aumenta el impacto posible de una ejecución de JavaScript en el origen.

**Mejoraría:** construir la impresión con React/DOM y textContent para datos; evitar HTML concatenado; aplicar una política de contenido compatible con la impresión y revisar todas las salidas documentales.

Referencia: [impresión QR](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/pages/InventarioPage.jsx:1303). [OWASP recomienda evitar estos destinos de HTML con datos no confiables](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html).

### H18 · Alto · Django fuera de soporte y dependencias pendientes de revisión completa
**Versiones verificadas.** requirements fija Django 4.2.30. Django 4.2 terminó su soporte extendido el 7 de abril de 2026; a la fecha de esta auditoría ya no recibe mantenimiento de seguridad. Migraría a una rama soportada, preferentemente una LTS compatible, con pruebas y ensayo de migración. [Calendario oficial](https://www.djangoproject.com/download/).

El lockfile incluye axios 1.7.9, react-router-dom 6.28.1, vite 6.3.6 y xlsx 0.18.5. La antigüedad no demuestra por sí sola que cada paquete sea explotable. SheetJS señala que la distribución npm de xlsx está desactualizada y documenta su distribución mantenida. Revisaría los usos reales de lectura/escritura antes de atribuir impacto. [Instalación oficial SheetJS](https://docs.sheetjs.com/docs/getting-started/installation/frameworks/).

**Mejoraría:** auditoría completa de dependencias directas/transitivas, versiones de Python y MySQL soportadas, actualizaciones programadas, lock reproducible de Python y CI. npm audit no pudo completarse por DNS; no se inventa un conteo de vulnerabilidades.

Referencia: [dependencias Python](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/requirements.txt:1) y [dependencias frontend](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/package.json:13).

### H19 · Alto · El catálogo puede quedarse sin multiplicador general
**Reproducido.** Una edición normal pudo desmarcar el único multiplicador general y el motor pasó silenciosamente a multiplicar por 1.

**Mejoraría:** garantizar exactamente una configuración general y exigir su reemplazo en la misma operación. Una configuración incompleta debe bloquear la publicación/cotización afectada y avisar, en vez de cambiar silenciosamente el margen. Validar rangos de costos, metrajes y multiplicadores, preservando los cargos negativos intencionales como “Sin tapa”.

Referencia: [edición del multiplicador](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/listaprecios/views.py:88) y [valor de respaldo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/listaprecios/services.py:22).

### H20 · Alto · Abrir la configuración de permisos cambia el acceso de auxiliares
**Reproducido.** Sin una fila de RolePermission, un auxiliar consultó caja con 200. El administrador consultó la lista de permisos, que creó filas vacías mediante GET. Después, el mismo auxiliar recibió 403.

**Mejoraría:** sembrar configuración explícita en una migración o acción de administración; GET nunca debe cambiar autorización. Unificar los permisos base usados por la API y por /user/, eliminar alias ambiguos progresivamente y probar los roles sin configuración y con configuración vacía.

Referencia: [GET crea roles vacíos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:322), [permisos por defecto](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/permissions.py:53) y [permisos de sesión](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:294).

### H21 · Alto · Administrar usuarios concede acceso a privilegios totales
**Reproducido; decisión de política por explicitar.** Un usuario no administrador con ADMINISTRAR_USUARIOS pudo cambiar su propio rol a administrador. Si ese permiso equivale deliberadamente a administración total, debe mostrarse así; si se delega para altas/bajas, su alcance es excesivo.

**Mejoraría:** separar altas/bajas, restablecer contraseñas y asignar privilegios; impedir autoelevación y proteger al último administrador. Registrar cambios de rol y revocar sesiones según corresponda.

Referencia: [gestión de usuarios](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:393) y [rol escribible](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/serializers.py:15).

### H22 · Alto · Despliegue puede ocultar errores y carece de recuperación comprobada
**Código/documentos; VPS no inspeccionado.** El script remoto canaliza instalación/migraciones a tail. El pipefail local no se hereda automáticamente al shell remoto; el éxito de tail puede ocultar el fallo anterior. La comprobación final imprime el estado HTTP, pero no exige el resultado esperado. El script actual no hace backup previo ni rollback automático.

**Mejoraría:** ejecución remota que propague fallos, releases identificadas por commit, build reproducible, pruebas previas, verificación real de salud y publicación reversible. Migraciones diseñadas para compatibilidad entre releases. Backups cifrados, fuera del repo/servidor y restauración ensayada con tiempos medidos. Automatizar frontend/backend con versiones compatibles.

Referencia: [script de deploy](/Users/stiven/Desktop/Coding/pruebaLottusKemi/deploy_backend_vps.sh:37) y [verificación final](/Users/stiven/Desktop/Coding/pruebaLottusKemi/deploy_backend_vps.sh:51). La ausencia en el repositorio no demuestra que el proveedor no tenga backups; hay que comprobarlos.

### H23 · Alto · La verificación actual no protege los flujos críticos
**Reproducido.** Los tests de ordenes y suministros son plantillas vacías. Las 21 pruebas de precios pasan, pero ejecutar el descubrimiento completo falla porque test_dashboard consulta una tabla al importar el módulo, antes de crear la base de pruebas. ESLint ignora JSX; no hay pruebas frontend ni workflows CI encontrados en estos repositorios.

**Mejoraría:** reparar el descubrimiento, cubrir dinero/permisos/inventario primero, habilitar lint para JS/JSX y pruebas de interacción. Añadir verificaciones obligatorias de migraciones, dependencias y build. No perseguir un porcentaje global: exigir pruebas de los invariantes y de cada fallo reproducido.

Referencia: [tests órdenes](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/tests.py:1), [tests suministros](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/tests.py:1), [importación problemática](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/test_dashboard.py:8) y [selección de archivos ESLint](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/eslint.config.js:11).

## Otros problemas concretos y mejoras técnicas

### H24 · Medio · El costo total omite telas/cueros del modelo nuevo
**Reproducido.** Un ítem con costo base 100 y tres unidades de tela a 20 devolvió costo_total=100, cuando corresponde 160 si esa tela integra el costo. El serializador suma los campos heredados y costos adicionales, pero no telas_cueros.

**Mejoraría:** una función de costo integral con Decimal, migración de la representación heredada y regla contra doble conteo. Conciliar el costo unitario con el costo de grupo y con lo que calcula la interfaz.

Referencia: [costo calculado](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:240) y [costo de tela convertido a float](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/models.py:134).

### H25 · Medio · Selectores cargan listas truncadas
**Reproducido en API y confirmado en frontend.** Al pedir 1000 proveedores con 103 existentes, llegaron 100 y una siguiente página. AppContext conserva solo results e ignora next. El mismo patrón afecta clientes.

**Mejoraría:** autocompletado con búsqueda y paginación real, o recorrido explícito cuando el catálogo deba cargarse completo; orden estable de resultados. No usar tamaños enormes como sustituto de paginación.

Referencia: [carga de proveedores y clientes](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/AppContext.jsx:110) y [tope de 100](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:261).

### H26 · Medio · Listados pesados y datos duplicados en el navegador
**Código; sin mediciones de latencia productiva.** Inventario y facturas carecen de paginación declarada y no hay paginación global DRF. Facturas descarga primero el listado y después todas las facturas con detalle usando full=true. Ventas permite listado completo y paginación manual sin un tope central.

**Mejoraría:** paginar y filtrar en servidor, cargar detalles al expandir, endpoints agregados para indicadores y exportación dedicada. Medir consultas por endpoint, tamaño de respuesta y percentiles de latencia antes de añadir caché o índices. Completar prefetch en detalles donde aún hay accesos por fila.

Referencia: [facturas](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/views.py:200), [doble carga de facturas](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/pages/FacturasProveedorPage.jsx:164), [inventario completo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/pages/InventarioPage.jsx:215) y [paginación de ventas](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1020).

### H27 · Medio · Productos de órdenes tienen validación insuficiente
**Reproducido.** La API aceptó una orden con cantidad cero y una referencia perteneciente a un proveedor diferente. Rechazar la lista vacía es correcto, pero no basta.

**Mejoraría:** serializador de escritura por detalle, cantidad estrictamente positiva, referencia/proveedor coherentes y cantidades/metrajes dentro de límites razonables. Hacer lo mismo con pedidos de tela y cambios directos de detalles.

Referencia: [validación y creación de detalles](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/serializers.py:170).

### H28 · Medio · Sesiones, tokens y limitación de intentos
**Código; configuración efectiva del proxy pendiente.** Los tokens están en localStorage, el acceso dura ocho horas y no se configura rotación/lista de revocación de refresh tokens. Cerrar sesión limpia el navegador, pero no invalida una copia del token. No hay caché compartida configurada para los throttles.

**Mejoraría:** política explícita de sesión/revocación, acceso más corto con renovación, MFA para perfiles privilegiados y protección adicional de administración. Evaluar cookies HttpOnly/SameSite junto con CSRF y CORS antes de migrar. Compartir contador de intentos entre procesos y configurar correctamente IPs/proxy. Añadir timeout a las peticiones y recuperación visible cuando /user/ falla: actualmente un error no 401 puede dejar un loader indefinido.

Referencia: [JWT y throttling](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/lottusPedidos/settings.py:314), [API central](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/services/api.js:6), [sesión](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/AppContext.jsx:67) y [ruta privada](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/PrivateRoute.jsx:24).

### H29 · Medio · Arquitectura y estado frontend dificultan cambios seguros
**Código.** InventarioPage tiene 2449 líneas, FacturasProveedorPage 1873, Ventas 1821; ordenes/views.py 2259 y suministros/serializers.py 1008. Conviven React Query, cargas manuales, datos de servidor en contexto y lógica duplicada de formularios/costos.

**Mejoraría:** extraer gradualmente servicios de caja, cobros, pagos, inventario y estadísticas; vistas pequeñas y reglas probadas. En frontend, servicios por dominio, hooks de consulta/mutación, claves coherentes e invalidación explícita. Separar tablas, filtros, formularios e impresión. Adoptar contratos API/OpenAPI y tipos graduales. Conservar un monolito modular: esta escala no justifica repartir los problemas en microservicios.

Referencia: [vistas órdenes](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1), [inventario](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/pages/InventarioPage.jsx:1), [contexto con listas](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/AppContext.jsx:51).

### H30 · Medio · Cargas de imágenes y correos no tienen controles uniformes
**Código.** La subida de lista de precios lee todo el archivo y confía en extensión/content-type, a diferencia de otros módulos que usan validación real de imagen. No se observa límite propio en esa acción. PQRS envía correos dentro de la petición y responde éxito aunque el helper de correo devuelva fallo.

**Mejoraría:** servicio compartido de imágenes con límites de bytes, dimensiones, cantidad y formato real, y limpieza de archivos huérfanos. Correo con registro persistente de pendientes, envío posterior al commit, reintentos y estado visible. No afirmar “enviado” cuando solo quedó registrado.

Referencia: [upload de catálogo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/listaprecios/views.py:317), [PQRS](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/paginaweb/views.py:415) y [envío de correo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/paginaweb/emails.py:45).

### H31 · Medio · Fechas de negocio inconsistentes
**Código.** Se mezclan date.today(), timezone.now().date() y timezone.localdate(). En caja se obtiene una fecha UTC y luego se interpreta su medianoche en Bogotá, con riesgo de desplazar el día de negocio por la noche.

**Mejoraría:** usar fecha local de negocio explícita, conservar instantes en UTC, definir el período comercial del día 6 al 5 una sola vez y probar sus bordes, diciembre/enero y operaciones nocturnas.

Referencia: [fecha del dashboard](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:78) y [rango diario de caja](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1193).

### H32 · Medio · Trazabilidad financiera y controles de datos
**Código/propuesta.** Caja referencia documentos principalmente mediante texto de concepto. ComprobanteEgreso no conserva campos estructurados de creador/aprobador y fechas de aprobación. Hay eventos de remisiones, pero no una bitácora equivalente para todos los cambios financieros.

**Mejoraría:** relaciones explícitas movimiento↔documento↔pago↔reversión, usuario/fecha/motivo y versión de los valores anteriores. Reconciliación automática de saldos, cobros y pagos; períodos cerrados; auditoría de exportaciones y cambios de permisos. Definir cómo tratar sobrepagos, anticipos y saldos a favor, en vez de aceptar números negativos sin significado documentado.

Referencia: [modelos caja y egresos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/models.py:170) y [abonos](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/views.py:1728).

### H33 · Medio · Identificadores y estructura de datos limitan evolución
**Código.** Los ítems de factura reciben prefijo de dos letras y número aleatorio entre 1000 y 9999: hay 9000 valores por prefijo, colisiones crecientes y un bucle sin salida al agotarse. Coexisten DetalleFactura heredado e Inventario como fuentes de productos, así como telas heredadas y múltiples telas nuevas. Venta.sede es texto con dos opciones mientras suministros dispone de Sede.

**Mejoraría:** identificador técnico estable y número visible separado; generador determinista con unicidad y manejo de colisiones. Consolidar las fuentes de verdad mediante migraciones verificadas. Unificar sedes con relaciones y conservar instantáneas de datos comerciales donde haga falta historial.

Referencia: [generador de ítems](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/suministros/serializers.py:505), [sede en ventas](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/ordenes/models.py:73).

### H34 · Medio · Documentación y operación no reflejan una única realidad
**Documentos/código.** generalidades habla de PostgreSQL y nombres de páginas que no coinciden con la implementación MySQL actual. Las guías discrepan sobre usuario del servicio, ruta y entorno virtual. lista_precios es un plan antiguo: el módulo ya existe y sus categorías/multiplicadores evolucionaron. El README frontend conserva la plantilla de Vite.

**Mejoraría:** guía única de arranque, configuración y despliegue; diagrama de dominios; diccionario de estados/permisos; reglas de negocio ejecutables en tests; decisiones de arquitectura fechadas. Versionar las guías sin secretos. Añadir checks de salud, errores con identificador de petición, métricas y alertas accionables; verificar backups y restauraciones en una revisión de infraestructura aparte.

Referencia: [contexto general](/Users/stiven/Desktop/Coding/pruebaLottusKemi/generalidades.md:1), [plan de precios](/Users/stiven/Desktop/Coding/pruebaLottusKemi/lista_precios.md:1), [guía backend](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend/deployment_guide.md:24), [README](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/README.md:1).

## Mejoras de experiencia de uso

Estas recomendaciones se basan en estructura y flujos del código; no sustituyen una prueba de usabilidad en escritorio, tablet y teléfono.

1. **Un expediente por venta:** reunir cotización, compromisos con cliente, cobros, órdenes, telas, recepción, remisiones y novedades. Mostrar qué falta y quién debe actuar.
2. **Formularios con borrador y recuperación:** evitar perder una venta/factura larga ante sesión caducada, cierre de modal o red intermitente. Advertir solo cuando existan cambios sin guardar.
3. **Errores junto al dato:** asociar el mensaje del servidor con la fila/campo afectado; conservar todos los datos al fallar. Diferenciar prohibición, validación y problema de conexión.
4. **Acciones claras por estado:** mostrar por qué no puede editarse, pagarse o entregarse un documento. Evitar botones visibles que terminarán en un 403 previsible.
5. **Tablas operativas:** búsqueda consistente, filtros persistentes en URL, rango de fechas común, totales del conjunto filtrado, selección de columnas y exportación con los mismos filtros.
6. **Un solo modal accesible:** reutilizar el componente existente y completar foco inicial, confinamiento de foco, devolución de foco y nombre accesible. Hoy conviven dos componentes Modal, además de implementaciones propias.
7. **Accesibilidad práctica:** navegación por teclado, etiquetas asociadas, estados anunciados, contraste medido y botones de icono con nombre. Priorizar caja, ventas y bodega.
8. **Impresión coherente:** plantillas compartidas, importes estructurados, fecha y versión del documento, pruebas de varias páginas y contenido extenso. Mantener la regla solicitada de imprimir “Pagado” en egresos; no cambiarla silenciosamente. Su alcance documental debe estar explicado a los operadores.
9. **Uso móvil para bodega y transporte:** escaneo de QR, botones amplios, formularios breves, estado de conexión y confirmación inequívoca. Un modo sin conexión requiere cola e idempotencia y debe diseñarse después de asegurar el servidor.
10. **Notificaciones y cargas uniformes:** loaders locales y toasts accesibles, con duración apropiada y detalles recuperables. Hay varias implementaciones de toast que pueden converger.

Referencias: [modal UI](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/components/ui/Modal.jsx:11), [modal alternativo](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/components/Modal.jsx:1), [impresión de egreso](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/components/ComprobanteEgresoReceipt.jsx:24).

## Evolución funcional que aportaría más valor

Son propuestas para acordar con el negocio después de resolver los fallos; no todas tienen que convertirse en módulos nuevos.

| Mejora | Valor y primer alcance |
|---|---|
| Cotizaciones persistentes | Número, cliente, asesor, vigencia, versión de precios, descuento autorizado y conversión a venta sin redigitar. El carrito actual vive solo en localStorage y usa una clave común entre usuarios del navegador. |
| Venta con líneas propias | Cantidad, variante, tela, opciones, precio y compromiso por producto. Hoy Venta guarda principalmente un total y las referencias están distribuidas en compras/inventario. Permitiría margen y entregas parciales verificables. |
| Flujo completo de mercancía | Cotización → venta → compra/reserva → recepción → preparación → despacho → entrega, con identificadores estables y responsables. |
| Recepción parcial de compras | Comparar pedido, mercancía recibida y factura; faltantes, diferencias y devoluciones por proveedor. No generar inventario sin relación clara con la recepción. |
| Cartera por cliente | Saldos vencidos, antigüedad, promesas de pago, anticipos/saldos a favor y seguimiento de cobro, calculados desde aplicaciones verificables. |
| Cuentas por pagar | Vencimientos, descuentos por pronto pago, pagos parciales y programación de transferencias sin perder la historia por factura. |
| Conciliación bancaria | Referencia bancaria, soporte, fecha efectiva y vínculo a cada línea de pago; coincidencias sugeridas y excepciones por revisar. |
| Cajas por sede y turno | Apertura, responsable, efectivo esperado/contado, diferencias y aprobación de ajustes. El cierre actual registra principalmente texto y mantiene el saldo. |
| Inventario reservable | Disponibilidad real separada de estado físico, historial de movimientos, conteos cíclicos, reparación, consignación y devolución. |
| Entregas parciales comprobables | Cantidad entregada/pendiente por línea; evidencia de recepción, novedades, devolución y reasignación sin duplicar reservas. |
| Precio y margen versionados | Guardar el precio aceptado en la cotización/venta; mostrar impacto de cambios de multiplicador; márgenes y descuentos basados en costo integral. |
| Comisiones explicables | Reglas por período, reparto de ventas compartidas y tratamiento de anulaciones/cobros/devoluciones. Un reporte debe explicar de dónde sale cada importe. |
| Atención posterior a la venta | Enlazar PQRS, garantías, reparaciones y visitas con venta/producto; responsable, fecha objetivo y evidencia de solución. |
| Tablero de excepciones | Pedidos atrasados, telas pendientes, mercancía recibida sin facturar, pagos sin conciliar, entregas próximas y documentos inconsistentes. Priorizar acciones sobre gráficos decorativos. |
| Integración contable/fiscal | Definir si el alcance exige integración con contabilidad y facturación de ventas. El módulo de FacturaProveedor no demuestra que exista esa cobertura. Evaluarla con las personas responsables antes de diseñar obligaciones o reglas tributarias. |
| Calidad y exportación de datos | Detección de duplicados de clientes, teléfonos/direcciones normalizados, trazabilidad de cambios y exportaciones por permisos. Reglas claras de conservación y acceso a información personal. |

Referencia de cotizaciones actuales: [carrito local](/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSW/src/hooks/useCotizacionCart.js:3). Las propuestas de precios respetan que ahora el precio por grupo es global y el multiplicador una entidad independiente; no se debe volver al diseño antiguo del documento de planeación.

## Orden de ejecución recomendado

| Etapa | Trabajo | Condición para avanzar |
|---|---|---|
| 1. Contención e integridad | H01–H12, H14, H16–H17; probar copias recuperables antes de correcciones de datos | Ningún error deja cambios parciales; no hay acceso cruzado ni aprobación por rutas alternativas; identidad de inventario preservada |
| 2. Exactitud y concurrencia | H13, H15, H19–H21, H24, H27, H31–H33 | Caja/abonos/facturas concilian; cifras compartidas correctas; pruebas simultáneas MySQL sin duplicaciones |
| 3. Calidad de entrega | H18, H22–H23, H28, H30, H34 | Versión soportada, CI útil, despliegue y recuperación ensayados, errores y respaldos observables |
| 4. Rendimiento y mantenimiento | H25–H26, H29 y componentes UI comunes | Listados paginados, detalles bajo demanda y mediciones con volumen representativo |
| 5. Evolución comercial | Cotizaciones persistentes, líneas de venta y excepciones; luego cartera, logística y conciliación | Flujo de punta a punta probado con los usuarios de cada rol |

Las etapas 1–3 pueden solaparse según responsables; son un orden de riesgo y dependencias, no una estimación de calendario. No hay información suficiente sobre equipo, volumen, datos históricos y despliegue real para prometer plazos.

## Criterios mínimos de aceptación

- Todo fallo de una operación financiera conserva exactamente el estado anterior.
- Ningún movimiento normal tiene importe negativo ni puede cambiar arbitrariamente el saldo.
- Cada pago confirmado se aplica una sola vez; cada reversión tiene una referencia verificable.
- Un usuario no puede consultar/modificar una venta ajena por otra ruta; los costos no viajan a roles no autorizados.
- Editar una factura conserva identificadores, QR, historial, costos y reservas existentes.
- Productos y facturas cuadran con importes calculados en servidor; los descuentos y anticipos son datos estructurados.
- Una venta de 300 compartida entre tres atribuye 100 a cada persona y 300 al total de empresa; anuladas excluidas según la regla de reporte.
- La misma unidad no puede reservarse simultáneamente en dos remisiones activas.
- Pruebas completas, lint de JSX, migraciones y build terminan correctamente en un entorno aislado.
- Configurar staging con DEBUG=False jamás selecciona producción.
- Restauración de un backup y recuperación de un despliegue fallido están demostradas.
- Los controles del PDF exigidos por el negocio y los flujos actualmente correctos siguen funcionando.

La revisión de datos históricos debe ejecutarse primero en una copia: buscar comprobantes/facturas pagados sin movimiento esperado, saldos no reconciliables, reservas duplicadas y discrepancias de costos. Este informe demuestra que el código permite esos estados; **no demuestra cuántos existen en producción**.

