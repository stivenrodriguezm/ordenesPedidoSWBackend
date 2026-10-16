# Validación (2026-10-02)

## Continuación 2026-10-08 — Perfiles de IA y entrenamiento desde el chat (D18)

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **326 OK (9 omitidas MySQL)**; 7 nuevas en `test_asistente_perfiles.py` (permisos, validación, documentos .md/.pdf, capacidad, áreas restringidas en declaración y ejecución, aprendizaje por usuario/perfil, pausar/borrar) |
| Backend MySQL 8.4 desechable | **326/326 OK** |
| Frontend | **141/141 en 29 suites** (nuevas: PerfilesIA 3, Chat +1); lint 0 errores (20 avisos previos); build OK |
| `pruebasv3` | Solo `ordenes 0058` aplicada tras respaldo completo; 0057 (Bancos) sigue sin aplicar por falta de autorización explícita |
| Navegador + Gemini real | Perfil creado desde plantilla con documento .md; la respuesta citó el documento y usó solo herramientas de ventas; 👎 con motivo, «Enseñar» y «Lo aprendido» funcionan; 1440 px y 390 px. Corregido: el panel «Lo aprendido» quedaba bajo la cabecera (ahora en portal) y pie móvil compacto; se cerró la ventana en la que un segundo clic tras crear podía duplicar el perfil. Documento ficticio, aprendizajes y conversación de prueba borrados; token revocado. El perfil «Analista de ventas» se conservó porque el usuario lo editó durante la prueba |

## Continuación 2026-10-08 — Chat gerencial con IA (Gemini) y Postferia

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **322: 312 OK + 10 omitidas** (8 nuevas en `test_asistente.py`, Gemini simulado) |
| Backend MySQL 8.4 desechable | **322/322 OK** (se corrigió que la verificación de conexión del asistente cerraba la conexión dentro de una transacción) |
| Frontend | **133/133 en 26 suites** (Markdown 3, Chat 4); lint 0 errores; build OK |
| Gemini real sobre `pruebasv3` | 14 herramientas responden en ≤ 0,8 s; preguntas reales respondidas con datos en 16–50 s; 3.8-flash saturado/colgado → respaldo 3.5-flash; formato colombiano reforzado en el contexto; conversaciones de prueba borradas y token revocado |

## Continuación 2026-10-08 — campos obligatorios, servicios y ajustes, vínculos e imágenes idénticas

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **314: 304 OK + 10 omitidas** |
| Backend MySQL 8.4 desechable | **314/314 OK**; apagado y borrado |
| Frontend | **126/126 en 24 suites**; lint 0 errores; build OK |
| Navegador (`pruebasv3`, ningún POST llegó al servidor) | imágenes de OP y de tela generadas desde /ordenes/nuevo, /telas y Ventas: iguales (tabla blanca, encabezados y alturas originales); venta 2627: el select de "Pedidos anteriores" ofrece los 3 productos y "No es de esta venta"; editor: solo se marca el campo que falta y el servicio sin valor |

## Continuación 2026-10-08 — pedidos desde la venta con imágenes, estado de tela y observación

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **312: 302 OK + 10 omitidas** (2 nuevas en `test_gestion_telas.py`) |
| Backend MySQL 8.4 desechable | **312/312 OK**; apagado y borrado |
| Frontend | **120/120 en 24 suites** (se eliminaron las pruebas de `RechazoLineaModal` y del `prefill`); lint 0 errores; build OK |
| Navegador (`pruebasv3`, POST interceptados: nada se escribió) | 2 órdenes (KRF, T&C) con fecha/tela/observación → `pedido_99901.png`, `pedido_99902.png`; telas: tela y cuero → 2 pedidos (`pedido_material_*.png`), imágenes revisadas e idénticas a las de /pedidos y /telas. Token revocado, imágenes borradas |

## Continuación 2026-10-08 — tela como en /telas (material, referencia, color) y formulario de /telas desde la venta

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **310: 300 OK + 10 omitidas** (8 en `test_gestion_telas.py`) |
| Backend MySQL 8.4 desechable | **310/310 OK**; apagado y borrado |
| Frontend | **124/124 en 26 suites**; lint 0 errores; build OK |
| Navegador (`pruebasv3`, sin guardar) | editor con Tela/Cuero, referencia, color, proveedor y cantidad (dm). Token revocado, capturas borradas |

## Continuación 2026-10-08 — tela por producto, pedido de telas y gestión (D15b)

| Comprobación | Resultado |
|---|---|
| Backend SQLite | **308 descubiertas: 298 OK + 10 omitidas** (requieren MySQL); 6 nuevas en `test_gestion_telas.py` |
| Backend MySQL 8.4 desechable | **308/308 OK**; servidor temporal apagado y borrado |
| Frontend | **120/120 en 25 suites** (6 nuevas en `ProductosVenta.test.jsx`); lint 0 errores/20 avisos; build OK |
| Navegador (`pruebasv3`, sin guardar) | columna Gestión ("Atrasada"), barra de gestión con faltantes y botón deshabilitado, sección Tela en el editor con cantidad sugerida. Token revocado y capturas borradas |

## Continuación 2026-10-08 — precio de lista fuera del formulario, recargo y panel compacto

| Comprobación | Resultado |
|---|---|
| Backend SQLite | OK, 10 omitidas (requieren MySQL) |
| Backend MySQL 8.4 desechable | OK, sin omisiones; servidor temporal apagado y borrado |
| Frontend | **114/114 en 25 suites**; lint 0 errores/20 avisos; build OK |
| Navegador (`pruebasv3`, sin guardar) | recargo "Patas en acero" $150.000 → precio de lista $9.147.776 → $9.297.776 (antes: 400); panel en escritorio y a 390 px sin desborde horizontal; esqueleto al expandir |

## Continuación 2026-10-07 — rediseño de productos de la venta (D15a) y pestaña de Calidad de clientes

| Comprobación | Resultado |
|---|---|
| Backend, SQLite aislada | **302 descubiertas: 292 OK + 10 omitidas** (concurrencia, requieren MySQL) |
| Backend, MySQL 8.4 desechable (127.0.0.1:33307, usuario exclusivo, apagado y borrado al terminar) | **302/302 OK**. `test_productos_venta_concurrencia` se ajustó a la regla nueva (texto para el proveedor obligatorio) |
| Frontend | **111/111 en 25 suites**; lint 0 errores/20 avisos; build OK |
| Visual (Playwright + Chrome, base `pruebasv3`, solo lectura) | venta expandida con panel de productos y editor; pestañas "Posibles duplicados" y "Fichas por corregir". Token de prueba revocado (`/api/logout/` 200) y capturas borradas |

## Continuación 2026-10-06 — P13-04, exportación y acceso de clientes/comisiones

Esta es la validación más reciente; las secciones siguientes conservan resultados históricos de entregas anteriores.

| Comprobación | Resultado |
|---|---|
| Backend completo, SQLite aislada sin `.env` | **369 descubiertas: 355 ejecutadas OK + 14 omitidas** por requerir MySQL |
| Backend completo, MySQL 8.4.11 desechable | **369/369 OK**, sin omisiones. Usuario exclusivo para `test_lottus`, puerto local 33307; base creada/destruida por Django y servidor apagado al terminar |
| Regresiones nuevas de backend | **29**: 16 en `ordenes/tests/test_exportaciones_clientes.py`, 13 en `ordenes/tests/test_exportaciones_comisiones.py` |
| Frontend completo | **143/143 en 28 suites**. 9 nuevas: 7 de Clientes y 2 añadidas a Comisiones; las dos suites afectadas suman 14 pruebas correctas |
| ESLint / Vite | **0 errores, 22 avisos** existentes; build en `.build-check/`, correcto en 1,68 s |
| Sintaxis / modelos | `py_compile` correcto en los archivos Python afectados; `makemigrations --check --dry-run` con `settings_test`: sin cambios; no hay migración nueva |

Cobertura nueva: permisos compuestos y revocación, exportación de ventas propias/compartidas sin duplicados, exclusión de clientes ajenos/sin ventas para vendedor limitado, directorio básico global preservado, historial sin ventas ajenas del mismo cliente, notas fuera de alcance rechazadas sin cambios y pérdida de alcance incluso para su autor; conteo de consultas constante al aumentar ventas (≤15). XLSX con más de 100 filas y filtro completo, nueve columnas permitidas, documento con ceros/teléfono con `+` conservados, sin fórmulas en XML; caracteres XML inválidos rechazados sin modificar originales; validación de búsquedas extensas y límite explícito 413. Auditoría sin búsquedas personales y fallo de auditoría sin archivo. Comisiones: CSV y agregados personales, tasas específicas ajenas omitidas, acceso global existente, roles limitados diferentes de vendedor, exportación ajena negada, controles de edición genérica/período cerrado, totales actualizados tras recalcular; texto potencialmente ejecutable como fórmula neutralizado, importes negativos legítimos conservados.

UI: filtros aplicados, descarga completa aunque haya varias páginas, deshabilitado durante búsqueda/carga, permiso de sesión y respuesta de servidor, doble clic, errores 403/413 legibles (incluido JSON recibido como Blob), sin falso mensaje de éxito; historial limitado sin botón para añadir notas fuera de alcance. El filtro local por nombre en comisiones no altera el archivo y se explica en pantalla.

Comandos: `DJANGO_ENV_FILE='' testenv/bin/python manage.py test --settings=lottusPedidos.settings_test --noinput`; MySQL con `settings_test_mysql` y variables `LOTTUS_TEST_MYSQL_*` dirigidas exclusivamente al servidor temporal; `npm run lint`, `npm test` y `npx vite build --outDir .build-check --emptyOutDir`. Para compilar en el sandbox, usar `PYTHONPYCACHEPREFIX=/private/tmp/lottus-p13-pycache` cuando la caché del sistema no sea escribible. Tras las suites completas se ajustó únicamente el indicador `historial_limitado` para explicarlo también en clientes con ventas parcialmente visibles; se recompiló Python y se volvió a ejecutar la suite de clientes (16/16).

Los errores SMTP y fallos de auditoría en los logs son inyecciones intencionales de pruebas. Persisten avisos de React Router y urllib3/LibreSSL. No se consultaron bases reales ni se desplegó. Interfaz validada con jsdom, sin prueba de descarga en navegador físico/Excel ni aceptación de operadores. No se añade una prueba de carrera específica de exportación de comisiones; las 14 de concurrencia existentes sí pasaron. D06d es provisional, D06b sigue abierto y las otras exportaciones/adjuntos quedan en `exportaciones-y-datos.md`. La generación auditada no prueba que el usuario haya recibido/abierto el archivo.

## Continuación 2026-10-06 — P13, calidad de clientes y alcance SIIGO

| Comprobación | Resultado |
|---|---|
| Backend completo, SQLite aislada y sin `.env` | **340 descubiertas: 326 ejecutadas OK + 14 omitidas** porque requieren MySQL |
| Backend completo, MySQL 8.4.11 desechable | **340/340 OK**, sin omisiones; servidor temporal en `127.0.0.1:33307`, usuario exclusivo con acceso solo a `test_lottus`, apagado al terminar |
| Nuevas pruebas de calidad | 22 de dominio/API: formato conservador, ceros iniciales/identidad intactos, criterios explicables, no filtración de candidatos ajenos, permisos compuestos, paginación, límites explícitos, versión alterada/vencida/desactualizada, selección de campos, originales exactos, rollback al fallar auditoría, idempotencia y alcance al reintentar |
| Nueva concurrencia real | Dos conexiones normalizan la misma ficha con la misma vista previa y claves distintas → **200 + 409**, una corrección y una bitácora; conserva teléfono original y nombre no seleccionado |
| Consultas | El número no crece al aumentar filas en el listado de calidad y se mantiene en el presupuesto de ≤15; no se midió latencia sobre datos operativos |
| Frontend completo | **134/134 en 27 suites**; 8 nuevas de interacción: selección explícita, cada permiso de escritura, reintento tras respuesta perdida, recarga ante conflicto, comparación, filtros/paginación y errores de revisión |
| ESLint / Vite | **0 errores, 22 avisos** en otros módulos; build correcto en `.build-check/` (1,63 s). Aviso de tamaño de bundle permanece |
| `py_compile` | Correcto en modelos, rutas, dominio, vistas, migración 0047 y ambas suites nuevas |
| `makemigrations --check --dry-run` | Sin cambios pendientes, usando `settings_test` y sin `.env` |

Comandos reproducibles: `DJANGO_ENV_FILE='' testenv/bin/python manage.py test --settings=lottusPedidos.settings_test --noinput`; para MySQL, usar `settings_test_mysql` con las variables `LOTTUS_TEST_MYSQL_*` apuntando **solo a un servidor desechable**, como exige la guarda del proyecto. Frontend: `npm run check`. No reutilizar credenciales ni base de operación.

La primera regresión de rollback esperaba que la API propagara una excepción Python. El manejador global existente responde 500; la prueba se ajustó para comprobar ese contrato y verificar que ficha/historial permanecen intactos. Las suites posteriores pasaron. Los mensajes de fallo SMTP son inyecciones de las pruebas existentes; persisten los avisos de urllib3/LibreSSL y React Router.

**Límites de esta continuación:** no se usaron datos reales, no se aplicó 0047 a una base persistente, no hubo despliegue, prueba en navegador físico ni aceptación de operadores (interfaz validada en jsdom). La fusión de clientes no está implementada: comparación y sugerencias no trasladan referencias. Los controles nuevos no acreditan todavía las rutas antiguas/exportaciones/adjuntos de P13-04. D06a confirma SIIGO sin intercambio por ahora; D06b continúa pendiente. Ver `alcance-contable-y-calidad.md` para continuar.

## Continuación 2026-10-06 — P10-05, conciliación operativa

Entrega local: cuatro cruces con evidencia, consulta protegida por permisos, filtros/paginación y exportación auditable. Preserva las reglas confirmadas de caja única y ventas sin vencimiento. Resultados finales de esta continuación:

| Comprobación | Resultado |
|---|---|
| Backend SQLite aislado, DJANGO_ENV_FILE vacío | 206 descubiertas; 199 ejecutadas correctamente, 7 omitidas por requerir MySQL |
| Backend MySQL 8.4.11 desechable local | **206/206 correctas**, incluidas las 7 pruebas de concurrencia existentes |
| Regresiones nuevas | **23** en ordenes/tests/test_conciliacion.py |
| Frontend completo | **80/80 correctas en 17 archivos**; 9 casos nuevos en Conciliacion.test.jsx |
| ESLint | 0 errores y los mismos 20 avisos previos |
| Compilación Vite en .build-check | Correcta, 1127 módulos, 2,88 s |
| Sintaxis Python | py_compile correcto en dominio, vistas, rutas y pruebas nuevas |
| Modelos/migraciones | makemigrations --check --dry-run: sin cambios; no hay migración nueva |

Verificado: permisos de cada cruce/lista/evidencia/exportación; ventas propias y compartidas sin duplicar dinero por joins; totales de todas las páginas; centavos y diferencias negativas; pagos pendientes/anulados excluidos de confirmados; reversiones completas y edición compensada; cobros duplicados o transferencias en caja detectados; historia sin vínculos no reconstruida por texto; varias facturas/descuentos sin falso faltante por comparar cada factura con el egreso completo; estados/proveedores nulos incoherentes; límites de fecha Bogotá; errores de validación 400; GET sin cambios (incluida cuenta ausente); exportación completa, límite 413 y auditoría sin parámetros arbitrarios/datos personales. El número de consultas del cruce cobros/caja se mantiene constante al crecer las filas y cumple el presupuesto de ≤15.

La prueba inicial de exportación en UI esperaba un segundo argumento que esta versión de React Query no pasa a mutationFn. Se corrigió esa expectativa del test; la suite completa posterior pasó. Los avisos de React Router y urllib3/LibreSSL y los errores SMTP simulados pertenecen al entorno/pruebas existentes.

MySQL se inicializó en una carpeta temporal nueva, con --no-defaults, puerto local 33307 y usuario limitado a test_lottus. Django creó/destruyó la base de pruebas y el servidor temporal se apagó al terminar. No se cargó .env ni se consultaron bases reales.

**Límites:** sin recorrido visual en navegador real, staging ni despliegue. La conciliación bancaria, aplicaciones monetarias por factura, resolución de diferencias y bloqueo/reapertura de períodos siguen pendientes; P10-05 permanece parcial. Las exportaciones son una lectura de datos actuales, no un cierre contable inmutable.

## Continuación P10 — caja única y cartera sin vencimiento

Alcance confirmado por el usuario en esta tarea: **una caja en una sede; las ventas no vencen por fecha**. Entrega local de P10-01/P10-04 con límites documentados en seguimiento.md y decisiones D10a–D10d. Las secciones anteriores/posteriores conservan resultados de otras entregas; los siguientes son los resultados de esta continuación.

| Comprobación | Resultado de esta entrega |
|---|---|
| Suite backend SQLite aislada, sin .env | 183 descubiertas; 176 ejecutadas correctamente y 7 omitidas por requerir MySQL |
| Suite backend MySQL 8.4.11 desechable, 127.0.0.1:33307 | **183/183 correctas**, incluidas 7 carreras simultáneas; tres nuevas de turnos |
| Regresiones P10 | 23 casos en test_tesoreria.py + 3 carreras en test_concurrencia.py |
| Suite frontend | **71/71 correctas en 16 archivos**, incluidas 10 pruebas nuevas de interfaz de tesorería |
| ESLint | 0 errores; 20 avisos preexistentes de hooks/fast refresh, sin avisos nuevos en los archivos de P10 |
| Build Vite en .build-check | Correcto; 1126 módulos, 1,46 s |
| Sintaxis Python | py_compile correcto en modelos, servicios, serializadores, vistas, rutas, migración 0039 y pruebas modificadas; caché en carpeta temporal |
| Modelos/migraciones y configuración | makemigrations --check sin cambios pendientes; manage.py check sin incidencias |

Se verificó: saldo inicial impuesto por servidor; conservación de dinero/historial; permiso de apertura/cierre; una sola apertura; conteos inválidos; faltante con motivo; doble cierre; ingreso y confirmación de recibo vinculados al turno; cierre antiguo bloqueado con turno activo; idempotencia; apertura/cierre concurrentes y carrera ingreso↔cierre. En cartera: alcance por venta, cliente y permisos; totales antes de paginar; ventas compartidas sin dividir/duplicar; pagos confirmados frente a pendientes/anulados; discrepancias históricas visibles; saldos a favor separados; promesas con validación/auditoría sin efecto monetario; GET sin escritura aunque envíe Idempotency-Key.

El primer ensayo MySQL detectó un error en la preparación de la nueva prueba de apertura (creaba de nuevo la cuenta principal que ya existe tras migraciones). Se corrigió a get_or_create y se repitió la suite completa, con 183/183 correctas. No fue un fallo de concurrencia de la implementación.

El motor temporal necesitó ejecución fuera del sandbox para iniciarse/conectar localmente; se usó exclusivamente una carpeta temporal nueva, puerto 33307 y usuario limitado a test_lottus. La base se creó/destruyó por el test runner; no se utilizó ninguna base del hosting ni se cargó .env. Las trazas de SMTP fallido pertenecen a pruebas existentes que simulan el error, no a envíos reales.

**Límites:** no se ejecutó recorrido visual en navegador real, staging ni despliegue; la migración 0039 solo se aplicó en bases de pruebas. Ajustes monetarios de diferencias, anticipos/aplicaciones entre documentos, cuentas por pagar y conciliación bancaria continúan pendientes. La revisión del backend conserva la advertencia preexistente de urllib3/LibreSSL.

Todo se ejecutó en local con datos ficticios. **Nada se desplegó ni tocó datos reales.**

## Comandos

Backend (`ordenesPedidoSWBackend`):

~~~sh
# Rápido: SQLite en memoria, sin .env ni salidas externas
DJANGO_ENV_FILE="" testenv/bin/python manage.py test --settings=lottusPedidos.settings_test --noinput
testenv/bin/python manage.py makemigrations --check --dry-run --settings=lottusPedidos.settings_test
testenv/bin/python manage.py check --settings=lottusPedidos.settings_test

# Integración/concurrencia: MySQL DESECHABLE (nunca el del hosting)
LOTTUS_TEST_MYSQL_HOST=127.0.0.1 LOTTUS_TEST_MYSQL_PORT=3307 LOTTUS_TEST_MYSQL_USER=lottus_test \
LOTTUS_TEST_MYSQL_PASSWORD=... testenv/bin/python manage.py test --settings=lottusPedidos.settings_test_mysql --noinput

# Diagnóstico de datos de SOLO LECTURA (sobre una copia autorizada)
python manage.py diagnostico_auditoria --json
~~~

Para el MySQL local se usó Homebrew `mysql@8.4` arrancado a mano (`mysqld --initialize-insecure` con datos en el scratchpad, puerto 3307, usuario `lottus_test` con permisos solo sobre `test_lottus`). En CI el job `concurrencia-mysql` usa un contenedor `mysql:8.0`. Requiere `requirements-dev.txt` (`cryptography` para la autenticación caching_sha2 de MySQL 8).

Frontend (`ordenesPedidoSW`):

~~~sh
npm run lint          # ESLint sobre JS/JSX
npm run test          # Vitest + Testing Library (jsdom)
npx vite build --outDir .build-check --emptyOutDir   # build de verificación, NO toca dist/
~~~

## Resultados

| Verificación | Entorno | Resultado |
|---|---|---|
| Línea base antes de corregir | SQLite, Django 4.2.30, Py 3.9 | 112 pruebas: 63 regresiones fallan (defectos vigentes) — `evidencia/p00-linea-base-regresiones.txt` |
| Suite completa tras P02–P07 | SQLite, Django 4.2.30, Py 3.9 | **137 OK** (4 omitidas: carreras, solo MySQL) |
| Suite completa | **MySQL 8.4.11** local desechable | **137 OK**, incluidas las 4 carreras con 3–5 conexiones simultáneas sincronizadas por barrera |
| Dependencias paso A (`requirements.txt` actual) | Py 3.9.6 sistema, SQLite y MySQL 8.4 | 137 OK |
| Ensayo paso B: Django 5.2.17, DRF 3.16.1, simplejwt 5.5.1 | Py 3.14, SQLite y MySQL 8.4 | 137 OK; aviso `CheckConstraint.check`→`condition` (cambiar al migrar) — `evidencia/pip-freeze-django52-ensayo.txt` |
| `makemigrations --check` | — | sin cambios pendientes |
| Suite tras P08 (consultas acotadas) | SQLite | **142 OK** (4 omitidas: carreras, solo MySQL) |
| Medición P08 antes/después | copia de producción en MariaDB 11.8 de Hostinger, Mac arm64, Py 3.9, n=3 | `evidencia/p08-linea-base-rendimiento.txt` → `evidencia/p08-despues-rendimiento.txt` |
| Lint frontend | ESLint 9 | 0 errores, 20 avisos (exhaustive-deps / fast-refresh) |
| Pruebas frontend | Vitest 3.2, jsdom 26 | 17 OK |
| Build frontend | Vite 6 | OK (a `.build-check/`) |
| `pip-audit` (2.10.1) `requirements.txt` original | PyPI advisory DB, 2026-10-02 | 65 avisos en 8 paquetes — `evidencia/pip-audit-requirements-actual.json` |
| `pip-audit` paso A | idem | 6 paquetes con avisos (django 4.2 sin soporte, drf, pillow, dotenv, requests, sqlparse: sus correcciones exigen Python ≥ 3.10) |
| `npm audit --omit=dev` antes / después de `npm audit fix` (sin `--force`) | npm 11.17 | 9 (1 crítica, 5 altas) → 3 (xlsx alta sin arreglo; react-router moderada requiere v7) — `evidencia/npm-audit-prod*.json` |

## Anexo A: las 26 observaciones

Todas tienen regresión con el **resultado corregido** como aserción, con el mismo nombre de la observación (buscar `def test_<nombre>`). Las 3 que documentaban controles correctos (`empty_order_is_correctly_rejected`, `remision_put_bypasses_patch_permission`, `remision_read_permission_can_delete`) siguen pasando. `interleaved_remision_validation_allows_double_reservation` se cubre en SQLite (verificación bajo bloqueo al guardar) y con carrera real en MySQL (`test_reserva_simultanea_de_una_unidad`).

## Límites (no ocultar)

- No hubo prueba en navegador real ni recorridos e2e (`test:e2e` pendiente, P07-03). Las pruebas de interacción son jsdom.
- No se revisó el VPS, nginx, backups reales ni datos de producción. El diagnóstico no se ha corrido sobre una copia real.
- Las carreras se probaron en MySQL 8.4 local; producción usa MySQL de Hostinger (versión no verificada).
- No hay control negativo de las carreras (no se reintrodujo el defecto para ver fallar la prueba en MySQL).
- La política de contenido (CSP) no se ha activado: requiere probarse con impresión, Cloudinary/Sirv y el dominio real.

## Continuación P10-02 — cuentas por pagar (2026-10-06)

| Comprobación | Resultado |
|---|---|
| Suite backend SQLite aislada, sin .env | 219 descubiertas; todas correctas, 8 omitidas por requerir MySQL |
| Suite backend MySQL 8.4 desechable (127.0.0.1:33307, carpeta temporal, sin .env) | **218/218** antes de agregar la prueba del listado de egresos, incluidas 8 carreras; nueva carrera: tres abonos simultáneos de 600 a una factura de 1000 → uno 201 y dos 400, caja descontada una vez |
| Regresiones P10-02 | `test_cuentas_pagar.py` 12 casos (parciales hasta pagar, fecha límite intacta, sobrepago, reserva por transferencia, confirmación por ambas rutas, anulación con reingreso, bloqueos de edición/borrado/egreso clásico, fecha en egreso clásico, filtros y totales, permisos, idempotencia, listado de egresos) |
| Suite frontend | **85/85** en 18 archivos (5 nuevas de Cuentas por pagar) |
| ESLint / build | 0 errores (20 avisos preexistentes) / correcto en `.build-check/` |
| `makemigrations --check` | sin cambios pendientes |
| Hallazgo durante la prueba en MySQL | sumar sobre las anotaciones encadenadas fallaba con `Unknown column` (SQLite no lo detecta): los totales se calculan con una sola consulta de columnas |
| Programación de pagos (D10g) | SQLite 227 (9 omitidas); **MySQL 8.4 desechable 227/227**, incluida la carrera de dos ejecuciones simultáneas de un mismo pago programado (un solo abono); frontend 88/88, lint 0 errores, build correcto |
| Conciliación bancaria (D10h) | SQLite 243 (10 omitidas); **MySQL 8.4 desechable 242/242** (incluida carrera: un cobro con dos movimientos simultáneos → 200 + 409); frontend 92/92, lint 0 errores, build correcto. Requiere `defusedxml==0.7.1` (nuevo en requirements) |
| Ensayo con extracto real (transacción revertida, copia de pruebas) | 265 movimientos leídos y validados (saldos 264/264 encadenados, resumen cuadrado); reimportación rechazada; recomendaciones únicas en 79/142 abonos; 0 filas guardadas tras el ensayo |
| Davivienda plano 200 posiciones | SQLite 246 (10 omitidas), **MySQL 246/246**, frontend 92; ensayo revertido con el archivo real: 106 movimientos validados, 0 filas guardadas |
| Davivienda PDF + plano | SQLite 250 (10 omitidas), **MySQL 250/250**, frontend 93; ensayo revertido con los archivos reales: 108 movimientos, resumen cuadrado, 0 filas guardadas. Nuevas dependencias de producción: `pypdf==5.4.0`, `cryptography==50.0.2` |
| P11-01 / P11-03 (recepción y entrega parcial) | SQLite 266 (12 omitidas); **MySQL 8.4 desechable 266/266**, incluidas las carreras: dos facturas sobre la misma línea (201 + 400) y dos confirmaciones simultáneas de una remisión (un solo cierre y una sola novedad); frontend 96/96, lint 0 errores (20 avisos), build correcto. Ensayo revertido en la copia con una orden real: unidad hereda venta/orden, línea 1/2 recibida, recibir de más = 400, `datos-ventas` 12 consultas, listado de órdenes 5 consultas; 0 filas guardadas |
| P11-02 / P11-04 / P11-05 (movimientos, conteos, flujo completo) | SQLite 281 (13 omitidas); **MySQL 8.4 desechable 281/281**, con nueva carrera (aperturas simultáneas de conteo y escaneo doble); frontend 102/102, lint 0 errores (20 avisos), build correcto. Ensayo revertido en la copia: conteo de zona con 290 unidades (3 faltantes, 1 sobrante ajustada con movimiento), devolución al proveedor, reactivación manual y cambio de unidad en remisión activa rechazados; 0 filas guardadas |
| P11-05 (lector QR para iPhone, verificación de remisión, reintentos) | SQLite 282 (13 omitidas); **MySQL 8.4 desechable 282/282**; frontend 106/106 (incluye el camino jsQR simulado y el permiso de cámara negado), lint 0 errores (20 avisos), build correcto. **Pendiente: prueba en iPhone real con https** (Safari bloquea la cámara en http) |
| P11-01 (rechazos al recibir) | SQLite 283 (13 omitidas); **MySQL 8.4 desechable 283/283**; frontend 108/108 (`RechazoLineaModal.test.jsx`: tope contra lo pendiente, motivo obligatorio, POST y marca en pantalla), lint 0 errores (20 avisos), build correcto. El formulario lleva `noValidate`: jsdom y Safari móvil no disparan `submit` cuando `type=number` queda fuera de `min/max` y la validación propia nunca se vería |
| P12-01 (precios, márgenes y simulación) | SQLite 290 (13 omitidas); **MySQL 8.4 desechable 290/290**; frontend 111/111 en 23 suites (`ExpedienteVenta.test.jsx`, `listaPreciosService.test.js`), lint 0 errores (21 avisos), build correcto |
| P12-02 (comisiones explicables por período) | SQLite 299 (13 omitidas); **MySQL 8.4 desechable 299/299**; frontend 116/116 en 24 suites (`ComisionesPage.test.jsx`: renderizado, filtros, reglas, recálculo, inmutabilidad y permisos), lint 0 errores (21 avisos), build correcto |
| P12-03 (posventa y garantías ligadas al producto) | SQLite 308 (13 omitidas); frontend 121/121 en 25 suites (`PosventaPage.test.jsx`: visualización de métricas y casos, búsqueda en vivo, permisos `VER_POSVENTA`/`GESTIONAR_POSVENTA`, apertura de radicación y gestión de expediente), lint 0 errores (21 avisos preexistentes), build correcto. Modelos, serializers y servicios de correo probados en `test_posventa.py` (9/9) |
| P14-01/P14-02 y combinación con P12/P13 (2026-10-06) | Backend **399 en SQLite (14 omitidas) y 399/399 en MySQL 8.4 desechable** (tras corregir el cierre de descargas en `test_evidencias_privadas`); frontend 156/156, lint 0 errores (22 avisos), build correcto. Respaldo de la copia restaurado en MySQL: conteos idénticos en 82 tablas; migrate idempotente |


## P16 — Web, navegación e IA (2026-10-08)

Corte completo: backend 309 pruebas (300 correctas y 9 omitidas de MySQL); frontend 135 correctas en 28 suites. Cierre dirigido tras los ajustes finales: 24 backend y 11 frontend correctas. Lint sin errores, 20 avisos existentes; build y sintaxis correctos. Consultas agregadas de solo lectura contra pruebasv3 y revisión visual con productos existentes; sin sembrar fixtures en esa base. Migración paginaweb 0005 aplicada tras respaldo; ordenes 0057 bloqueada por revisión automática a la espera de confirmación explícita. Sin publicación ni nueva respuesta real de Gemini. Comandos, límites y recuperación en [web-navegacion-ia.md](web-navegacion-ia.md).


## Corrección P16-07/08 (2026-10-08)

Se reproduce la causa en log: `OperationalError 2006` al guardar la respuesta después de esperar a Gemini y al guardar el error con el mismo socket muerto. Regresión de cierre de conexión antes de HTTP, reconexión del UPDATE, respuesta tardía, modelos permitidos, fallback, cuota/timeout y ausencia de filtración de mensajes del proveedor. Frontend verifica cambio de modelo/reintento y pérdida de red/reanudación sin nuevo POST. Corte completo: 319 backend, 9 omitidas MySQL; 137 frontend; lint 0 errores/20 avisos; build, py_compile y makemigrations --check correctos. Se comprobó Gemini real y gráfico con datos existentes. Detalle y evidencia visual en [chat-y-editor-compacto.md](chat-y-editor-compacto.md).
