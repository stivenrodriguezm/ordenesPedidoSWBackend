# Operación (borrador, P07)

Estado: **preparado, no ejecutado contra el VPS** (sin acceso autorizado en esta ejecución).

## P17-06 a P17-13 — Oficina, chat y automatizaciones IA

Entrega local validada en `localhost:3000/8000`, migraciones **0063 y, posteriormente, 0064 aplicadas con destinos explícitos en pruebasv3** tras respaldo parcial verificado de zonas/perfiles/migraciones. 0057 y merge 0061 siguen sin ejecutar. El motor de automatizaciones está arrancado en local; no se instalaron servicios en el VPS ni se publicaron cambios. La revisión P17-10 a P17-13 conserva la anchura del mapa con Comercial al doble y siete puestos, aula de Entrenamiento y chat integrado. Para el despliegue futuro usar destino explícito `ordenes 0064_entrenamiento_oficina_ia` tras inspeccionar las dependencias; el aula no incorpora cuentas humanas ni un sistema de exámenes.

Para usar y reiniciar el motor local, preparar el servicio del servidor, revisar calendarios/cola/resultados o recuperar una interrupción, seguir [automatizaciones-ia.md](automatizaciones-ia.md). Comando local: `LOTTUS_LOCAL_TEST_DB=1 testenv/bin/python manage.py ejecutar_automatizaciones_ia --continuo`. La variable no se debe configurar en producción. Plantilla de systemd preparada en `deploy/lottus-automatizaciones-ia.service.example`; instalación pendiente del despliegue autorizado. No aplicar migraciones globales que incorporen el retiro pendiente de Bancos.

## Lista de despliegue de la rama `auditoria-2026-10-02` (leer ANTES de subir al VPS)

Actualizada el 2026-10-06. El script de la raíz (`deploy_backend_vps.sh`) hace `git reset --hard origin/main`, `pip install -r requirements.txt`, `migrate`, `collectstatic` y reinicia gunicorn, pero **no respalda ni revisa el `.env`**. Por eso:

**Antes de desplegar**
1. **`.env` del VPS (bloqueante, H16).** Antes, con `DEBUG=False`, el código forzaba la base y el usuario de producción. Ahora con `DB_HOST` exige `DB_NAME`, `DB_USER` y `DB_PASSWORD` explícitos; si falta alguno, gunicorn no arranca (`ImproperlyConfigured` → 502). Confirmar en el servidor que **`DB_NAME` es la base de producción y no la de pruebas** (antes el valor del `.env` se ignoraba, así que puede tener uno viejo). Comprobar solo los nombres, sin imprimir valores: `grep -o '^[A-Z_]*=' .env`. **`DJANGO_SECRET_KEY` también es obligatoria** con `DEBUG=False` (≥ 32 bytes): sin ella gunicorn no arranca.
2. **Variables del proceso.** `.env` se carga con `override=False`: si `gunicorn.service` define `Environment=` para las mismas variables, esas mandan. Revisar `systemctl cat gunicorn`.
3. **Python del venv ≥ 3.9.** Lo exigen DRF 3.16, `pypdf` y `cryptography`, y es la versión probada: `venv/bin/python --version`.
4. **Respaldo verificado de la base de producción** (el script de la raíz no lo hace): `mysqldump --single-transaction --column-statistics=0 … | gzip`, seguido de `gzip -t` y un conteo de tablas. Guardarlo fuera del repo.
5. **Diagnóstico en una copia.** Restaurar el respaldo en una base aislada, correr ahí `migrate` y `diagnostico_auditoria --json` (ver `migracion-datos.md`). La migración `ordenes 0037` **se detiene** si el último saldo de caja es negativo.
6. **Commit en `origin/main`.** Llevar la rama a `main` y hacer push: el script solo trae lo que está en GitHub.

**Dependencias nuevas en `requirements.txt`** (las instala el `pip install` del script; revisar que su salida no tenga errores)
- `defusedxml==0.7.1`: lectura segura del Excel de Bancolombia (openpyxl).
- `pypdf==5.4.0` + `cryptography==50.0.2`: PDF de Davivienda (viene cifrado con AES; sin `cryptography`, la importación falla).
- Subidas de versión: DRF 3.16.1, simplejwt 5.5.1, Pillow 11.3.0, PyMySQL 1.2.3, python-dotenv 1.2.1, requests 2.32.5, sqlparse 0.5.5.

**Migraciones que aplicará `migrate`** (todas expansivas salvo `ordenes 0037`, que es de datos; detalle en `migracion-datos.md`)
- `ordenes`: 0036–0056 (0044–0048: margen y corrección de clientes; 0049 elimina los módulos de D-ALCANCE; 0050 crea Nómina y borra las tablas de comisiones; 0051 productos de la venta P15; 0052 "No aplica" del texto para el proveedor; 0053–0054 tela por producto (material, referencia, color) y gestión de la venta; 0055 servicios/ajustes de la venta y pedidos anteriores ajenos; 0056 Postferia y tablas del Chat).
- `suministros`: 0032–0039 (0039 elimina conteos y abonos parciales, D-ALCANCE).
- `listaprecios`: 0010–0011.
- `paginaweb`: 0004.
- `token_blacklist` (simplejwt).
- Toda la cadena está aplicada sin errores en `u756180748_pruebasv3` (copia de producción, MariaDB 11.8) desde el 2026-10-06, con respaldos previos en `respaldos_locales/`.

**Chat (asesor gerencial con IA, 2026-10-08)**
- Agregar `GEMINI_API_KEY=…` al `.env` del VPS (permisos 600; sin ella la página Chat dice "no configurado" y el resto funciona). Opcional `GEMINI_MODELOS` (por defecto `gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash`: el primero que responda; un modelo saturado se salta 10 min).
- El VPS necesita salida HTTPS a `generativelanguage.googleapis.com`.
- La respuesta se genera en un hilo del proceso de gunicorn (no choca con su timeout de 30 s): con `--workers 3` sync funciona; si gunicorn se reinicia a mitad de una respuesta, el mensaje queda como error a los 5 min y el usuario vuelve a preguntar.
- Permiso `USAR_ASISTENTE_IA`: solo administradores (tienen todos los permisos); ningún otro rol lo recibe solo.

**Después de desplegar**
1. `curl https://api.muebleslottus.com/api/health/` debe responder `ok`. Revisar `journalctl -u gunicorn` por `ImproperlyConfigured` o `ModuleNotFoundError` (pypdf, defusedxml).
2. **Publicar el frontend después del backend.** El frontend envía la cabecera `Idempotency-Key`, que el backend anterior no admite en CORS. Compilar con `npm install` (nueva dependencia `jsqr`, lector QR para iPhone) y `npm run build` en `ordenesPedidoSW/`, y subir `dist/`.
3. **La caché de throttling** se escribe en `.cache/django` dentro del repo, o en `DJANGO_CACHE_DIR`: debe poder escribirla el usuario de gunicorn.
4. **Cron:** `*/10 * * * * cd /home/stiven/ordenesPedidoSWBackend && ./venv/bin/python manage.py reintentar_correos`.
5. **Permisos nuevos** (no se asignan solos salvo CERRAR_CAJA, vía 0037):
   - VER_BANCOS, CONCILIAR_BANCOS;
   - VER_CALIDAD_CLIENTES, NORMALIZAR_CLIENTES (además de VER_CLIENTES/EDITAR_CLIENTE según acción);
   - VER_MARGENES;
   - VER_NOMINA, GESTIONAR_NOMINA;
   - EXPORTAR_CLIENTES.

   Se asignan desde Usuarios según `matriz-permisos.md`.
6. **Sesiones:** los refresh tokens rotan y se revocan al cerrar sesión. Los tokens vigentes siguen sirviendo hasta que vencen.
7. **Prueba de humo:** login; crear y confirmar un recibo; Bancos → Importar extracto en vista previa sin confirmar; Nómina → crear un cierre en borrador y borrarlo.

## Arranque local

- Backend: `testenv/bin/python manage.py runserver`. Sin `DB_HOST` usa SQLite local. Con `DB_HOST` exige `DB_NAME`, `DB_USER`, `DB_PASSWORD`. Variables del proceso > `.env`; `DJANGO_ENV_FILE` elige otro archivo (vacío = ninguno).
- Frontend: `npm start` (Vite, puerto 3000), `VITE_API_BASE_URL` por entorno. Compilar para publicar: `npm run build` (escribe `dist/`).

## Despliegue backend

`scripts/deploy/deploy_backend.sh <commit>` con `DEPLOY_HOST` y `DEPLOY_USER`. Preparación única (pendiente, P01-03):

1. Usuario de despliegue con llave SSH; deshabilitar acceso SSH por contraseña.
2. `sudoers`: `DEPLOY_USER ALL=(root) NOPASSWD: /bin/systemctl restart gunicorn, /bin/systemctl is-active gunicorn`.
3. `~/.my.cnf` (600) del usuario con credenciales de un usuario MySQL de respaldo (solo lectura + LOCK/SHOW VIEW).
4. `.env` del servidor con `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DJANGO_SECRET_KEY` (≥ 32 bytes); opcional `DJANGO_NUM_PROXIES=1` tras verificar `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` en nginx; `DJANGO_CACHE_DIR` escribible por gunicorn.
5. Cron: `*/10 * * * * cd <repo> && ./venv/bin/python manage.py reintentar_correos`.

El script: falla ante cambios locales en el servidor, fija el commit exacto, respalda y verifica el gzip, instala, `check --deploy`, migra, reinicia y exige `GET /api/health/` = ok; si la salud falla, vuelve el **código** al commit anterior (las migraciones aplicadas se conservan: deben ser expansivas).

## Recuperación

- Código: desplegar el commit anterior con el mismo script.
- Datos: restaurar el respaldo `pre_<sha>_<fecha>.sql.gz` en una base aislada, verificar (conteos, `diagnostico_auditoria`, login) y solo entonces decidir. Pendiente medir tiempos reales y ensayar (P07-05, D08).
- Credenciales: no reactivar credenciales expuestas; usar las de contingencia.

## Señales a vigilar (pendiente de instrumentar, P07-07)

`/api/health/` (503 = base caída), correos `fallido` en CorreoSaliente, 409 frecuentes de idempotencia o de saldo insuficiente, edad del último respaldo, errores 5xx en el log de gunicorn.

## P11 — Recepción, entrega parcial y movimientos (2026-10-06, preparada sin despliegue)

1. **Recibir:** en Registrar factura, por fila, elegir la OP y luego "Línea del pedido que llega". Si la orden tiene una sola línea con pendiente, se elige sola. La factura no puede recibir más de lo pedido. Cuando todas las líneas llegan, la orden pasa sola a "Recibido". Sin línea, la factura funciona como antes. Las órdenes ya marcadas "recibido" a mano no cambian.
2. **Consultar lo pendiente:** en Órdenes, al abrir el detalle, cada línea muestra "Recibidas x/y". Una línea con recibidas no se puede bajar por debajo de ellas ni borrar.
3. **Confirmar la entrega:** puede hacerlo el transportador asignado o alguien con CAMBIAR_ESTADO_REMISION (para transportistas externos). En "¿Algo no se entregó?" se marca el producto (o la cantidad, en productos de pedido) y el motivo. Eso vuelve a bodega y aparece en la siguiente remisión de la venta. La venta no se marca entregada mientras haya pendientes. Si no se entregó nada, usar "Registrar devolución".
4. **Historial y devolución al proveedor:** en Inventario, el botón de historial muestra cada movimiento de la unidad: qué cambió, quién, cuándo y con qué documento. Desde ahí se registra "Devolver al proveedor", con motivo obligatorio. La unidad deja de estar disponible y su línea de orden de pedido vuelve a quedar pendiente para la reposición. Una unidad que va en una remisión activa, o que está despachada o entregada, no se devuelve.
5. **Lo que ya no se cambia a mano:** "Por despachar", "Despachado" y "Devuelto al proveedor" los pone su proceso. Una unidad en remisión activa no cambia de disponibilidad ni de venta desde la edición; hay que despachar, entregar, devolver o anular la remisión.
7. **Cancelar, sustituir y reintentar:**

   | Operación | Cancelar | Sustituir | Reintentar |
   |---|---|---|---|
   | Remisión | Anular (libera las unidades) | Anular y crear otra con las unidades correctas | Repetir la misma confirmación no duplica nada |
   | Factura | — | Si llegó otra mercancía, devolver la unidad al proveedor y recibir la reposición en su factura | Con la misma clave de idempotencia no se duplica |
8. **Verificar con QR al despachar y entregar** (Remisiones → Despachar / Confirmar entrega → "Verificar productos con QR"): cada producto escaneado se marca como verificado. Un código que no va en la remisión se avisa de inmediato. Es opcional y no cambia nada en el servidor. Los productos escritos o de pedido no tienen QR.
9. **Celulares (la mayoría iPhone, D04d):** la cámara solo funciona en la dirección https. En http, incluido localhost por la red, Safari la bloquea. Si la cámara se negó: Ajustes → Safari → Cámara → Permitir. Sin señal, el botón de confirmar se desactiva; si una confirmación se envió y no llegó respuesta, repetirla no duplica nada.
10. **Prueba pendiente en un iPhone real**, tras desplegar o con un túnel https:
    - abrir Remisiones;
    - aceptar y negar el permiso de cámara;
    - leer etiquetas impresas antes y después de esta versión;
    - escanear dos veces seguidas la misma etiqueta;
    - activar el modo avión a mitad de una confirmación y reintentar;
    - confirmar una entrega parcial.
11. **Rechazos al recibir:** si llega mercancía que no se acepta (golpeada, tela equivocada), Órdenes → expandir la orden → "Registrar rechazo" en la línea, con cantidad y motivo. Lo rechazado no se factura ni crea unidades: la línea sigue pendiente y la reposición se recibe con su factura. Requiere permiso de crear facturas. Queda quién, cuánto y por qué, y "Rechazadas n" en la línea.

## Nómina de asesores (D12a, 2026-10-06, preparada sin despliegue)

Reemplaza a "Comisiones". Ruta: Finanzas → **Nómina** (`/nomina`; `/comisiones` redirige). VER_NOMINA consulta y GESTIONAR_NOMINA edita. Ninguno se asigna por defecto, porque muestra salarios.

1. **Configuración** (botón en la pantalla):
   - tabla descuento → comisión (por defecto: 0 % → 4,0 %, hasta 2,5 % → 3,9 % … hasta 25 % → 3,0 %);
   - abono mínimo para pagar la comisión (30 %) y bonificación por meta (1 %);
   - día de pago del básico (20) y texto del pago de la nómina ("entre el 6 y el 11");
   - "comisionar ventas desde": se fija al crear el primer cierre; las ventas anteriores se liquidaron fuera del sistema;
   - básico y meta por asesor.
2. **Precio de lista:** se registra en la venta (Nueva venta, Editar venta, edición rápida). Sin precio de lista, la venta se toma sin descuento (4 %). También se puede corregir en el cierre; ese cambio se guarda en la venta.
3. **Nuevo cierre:** propone el período comercial (del 6 al 5) y se puede cambiar. Calcula:
   - comisiones de las ventas del período más las pendientes de antes; se pagan con abono ≥ 30 %;
   - bonificaciones causadas en el período si se cumple la meta; se pagan desde el cierre siguiente, al entregar cada venta;
   - bonificaciones pendientes de cierres anteriores.
   Las ventas compartidas se dividen en partes iguales.
4. **Revisar:** el "Cierre general" tiene una fila por asesor: comisiones, bonificaciones, ajustes, total de nómina (pago 6–11), básico (pago día 20) y lo que queda pendiente. Cada asesor tiene su pestaña con las tablas de comisiones (precio de lista contra venta, descuento, abono, %, valor), bonificaciones y ajustes.
5. **Editar** (solo en borrador): precio de lista, %, valor, "pagar" sí o no, nota, básico, meta, "cumple meta" (automático, sí o no) y ajustes que suman o restan (adelantos, cuentas por cuadrar). "Recalcular" respeta lo editado a mano.
6. **Cerrar nómina:** lo pagado no vuelve a aparecer; lo pendiente pasa al siguiente cierre. "Reabrir" pide motivo y solo se permite si no hay un cierre posterior cerrado. "Exportar a Excel" genera una hoja de cierre general y una hoja por asesor.

## P13 — Calidad de clientes (2026-10-06, preparada sin despliegue)

1. La migración `ordenes 0047_correccion_cliente` agrega solo la tabla de historial; depende de 0046 y no normaliza registros ni asigna permisos. Fue aplicada por las suites a SQLite y MySQL 8.4 desechables, no a la base operativa ni a su copia persistente durante esta continuación. Ensayar en staging con respaldo antes de publicar backend y luego frontend.
2. Asignar `VER_CLIENTES` + `VER_CALIDAD_CLIENTES` para revisar; sumar `EDITAR_CLIENTE` + `NORMALIZAR_CLIENTES` a quien deba aplicar correcciones. Administrador conserva acceso completo. Los roles limitados revisan únicamente clientes de ventas visibles.
3. Abrir **Bases de Datos → Calidad de clientes**. En «Formato de las fichas», buscar, abrir ficha, comparar original/propuesta y seleccionar solo lo que corresponde. El historial identifica revisión, autor, fecha y valores exactos anteriores. No edita cédula/NIT, montos ni relaciones de documentos.
4. Una ficha modificada o una vista previa de más de 30 minutos devuelve conflicto: pulsar «Volver a cargar ficha», revisar y seleccionar de nuevo. Si se perdió la respuesta de red, reintentar sin cambiar la selección conserva la clave de la solicitud y evita duplicar el historial.
5. «Posibles duplicados» explica el criterio; «Comparar fichas» muestra diferencias. No hay fusión automática ni traslado/borrado. Más de 5000 clientes o grupos de más de 50 exigen preparar revisión por lotes; el error no significa que no existan duplicados.
6. No borrar la tabla de historial para volver a una versión anterior: se perderían los valores originales. Deshabilitar la nueva interfaz/permiso si se necesita retirar la función, conservando tabla y respaldo. No existe deshacer automático de correcciones; una recuperación requiere revisar el historial y los cambios posteriores antes de una corrección controlada.
7. SIIGO queda sin conexión/exportación por decisión D06a. No se requieren claves ni nuevas dependencias. P13-04 y D06b siguen abiertos para conservación y acceso a datos. La fusión ejecutable y la prueba con operadores permanecen pendientes.

## P13-04 — Descargas de clientes (2026-10-06, sin despliegue)

1. Publicar primero el backend que contiene `POST /api/clientes/exportar/`, y luego el frontend, cuando se autorice el despliegue. `openpyxl` ya está en dependencias. Este avance no agrega migraciones ni permisos; conservar los requisitos de migración de entregas anteriores. No se aplicó ninguna migración a bases persistentes aquí.
2. Revisar asignaciones existentes de `VER_CLIENTES`, `EXPORTAR_CLIENTES` y alcance de ventas. No conceder permisos en bloque. La ficha básica global se mantiene provisionalmente (D06d); exportación e historial comercial se limitan a ventas visibles para vendedor limitado. La pantalla explica por qué directorio y archivo pueden tener distintos clientes.
3. En staging con datos ficticios: exportar como vendedor principal, compartido y usuario global; comprobar inclusión/exclusión del cliente ajeno y sin ventas, más de una página, filtro y cero resultados. Revisar que cédula con ceros y teléfono `+` permanezcan literales, así como nombres que parecen fórmula. Probar permiso revocado y error/límite sin descargar archivo parcial.
4. Comprobar eventos `clientes.exportar` (usuario/fecha/alcance/conteos). Significan **generación**, no entrega o apertura del archivo. No contienen clientes ni búsquedas en texto. Un nuevo intento puede generar un nuevo evento; no reconstruir una descarga a partir de una huella HMAC ni registrar el filtro personal en logs para hacerlo.
5. Rechazo 413 exige acotar búsqueda de clientes; no subir límites sin medir recursos y validar que el archivo sea íntegro. 400 de formato XLSX exige revisar caracteres inválidos de la ficha mediante una corrección autorizada; el intento de exportación no modifica los datos. Si falla auditoría, se responde 500 y no se devuelve archivo; revisar servicio/base antes de reintentar, sin desactivar el control.
6. Si falla el frontend, corregir la descarga conservando los controles API. No recuperar disponibilidad volviendo a habilitar CSV global para vendedores o retirando autorización/auditoría. La reversión no necesita cambios de esquema. Mantener los eventos ya registrados.
7. Pendientes: recorrido en navegador real/Excel, otras exportaciones/impresiones, evidencias y acceso directo al almacenamiento; D06b para conservación/solicitudes y D06d para directorio/edición. Las pruebas locales no son aceptación operativa ni despliegue. Inventario concreto en `exportaciones-y-datos.md`.
