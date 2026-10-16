# P14 — Aceptación integral y publicación (2026-10-06)

Estado: todo lo de este documento se probó **en local** (SQLite y MySQL 8.4 desechables, y la copia `u756180748_pruebasv3`). Nada está desplegado. Lo que requiere operadores, el VPS o tu autorización está marcado como **pendiente**.

## 1. Recorridos por rol con la configuración real (P14-01)

`ordenes/tests/test_recorridos_por_rol.py` usa la foto de permisos de la copia de producción (`ordenes/tests/roles_reales.py`, solo códigos) y recorre por la API:

| Recorrido | Qué comprueba |
|---|---|
| Vendedor principal y compartido | El compartido ve la venta compartida y la remisiona; no ve ni remisiona la ajena. La principal crea su orden de pedido sin ver costos; el auxiliar sí los ve. Sin inventario ni recibos para el vendedor (así está configurado) |
| Auxiliar: compra para cliente y para stock | Orden con venta y orden de exhibición; las facturas ligadas crean una unidad "cliente" con su venta y otra "exhibición" sin venta. Cobro mixto: el efectivo entra a caja al momento; la transferencia queda pendiente y solo la confirma el administrador |
| Parcial, entrega, anulación y devolución | Recibir 2 de 3; la vendedora crea la remisión; el transportador real despacha y entrega una unidad y reporta la otra dañada; el auxiliar la devuelve al proveedor (la línea vuelve a pedir). Remisión anulada por el administrador libera la unidad. Recibo anulado por el administrador devuelve el saldo de la venta y la caja |
| Documento histórico | Orden marcada "recibido" a mano sin unidades ligadas y unidad anterior sin factura ni movimientos: se consultan, se remisionan y la bitácora empieza en ese momento |
| Pantallas nuevas | Cada una responde según el permiso que exige y la configuración real (tabla siguiente) |

Además, `test_flujo_completo.py` recorre cotización → entrega con el responsable de cada paso, y `test_aceptacion_integral.py` hace la jornada de caja: cobro mixto, reintento, abono a proveedor y arqueo.

### Lo que encontraron los recorridos en la configuración real (decisiones tuyas)

| # | Hallazgo | Efecto hoy | Decide |
|---|---|---|---|
| R1 | El auxiliar tiene "crear remisión para todas las ventas" pero **no** "crear remisión" | No puede crear remisiones; solo vendedores y administrador | Agregar CREAR_REMISION al auxiliar o quitarle el otro |
| R2 | Solo el administrador tiene APROBAR_RECIBO, APROBAR_EGRESO y EDITAR_RECIBO | Toda transferencia, aprobación de egreso y anulación de recibo pasa por el administrador | Es coherente con D01 (quien prepara ≠ quien aprueba); confirmar que es lo deseado |
| R3 | El vendedor no tiene CREAR_VENTA ni VER_CLIENTES | Las ventas las registra el auxiliar | Confirmar |
| R4 | El auxiliar no tiene las pantallas nuevas Bancos y Calidad de clientes; Nómina solo debe tenerla quien liquida (muestra salarios) | No aparecen hasta asignarlas | Asignar al publicar |
| R5 | El transportador solo tiene VER_REMISIONES | Ve y confirma solo sus remisiones (regla del rol) | Ninguna |

## 2. Condiciones adversas (P14-02)

| Condición | Cómo se cubre | Evidencia |
|---|---|---|
| Doble clic / reintento | Clave de idempotencia por contenido en altas financieras; restricciones únicas | `test_atomicidad_idempotencia` (venta, factura, egreso, cobro), `useIdempotencia.test`, `test_reintento_de_la_confirmacion_no_duplica`, escaneo repetido en conteos |
| Solicitudes concurrentes | Bloqueo de fila y transiciones condicionales | `test_concurrencia` en MySQL (7 carreras: confirmación de cobros, egresos con caja vacía, numeración, reserva de una unidad, conciliación bancaria, recepción de una línea y confirmación de entrega) |
| Respuesta perdida tras guardar | La repetición devuelve la respuesta original | `test_aceptacion_integral` (cobro reintentado), confirmación de entrega repetida → 200 sin duplicar |
| Dos pestañas | Borradores con dueño y versión; **sesión**: si dos pestañas renuevan a la vez, la segunda usa el token que guardó la primera en vez de cerrar la sesión (corregido el 2026-10-06; antes la rotación de P02-05 expulsaba al usuario de todas las pestañas) | `useBorrador.test`, `services/api.test.js` |
| Sesión expirada | Renovación automática con rotación; cierre de sesión revoca el refresh | `test_sesion`, `services/api.test.js` |
| Cambio de permisos con sesión abierta | Cada petición revalida permisos; cuenta desactivada no renueva | `test_token_vigente_revalida_permisos_y_cuenta_desactivada`, `test_usuario_desactivado_no_renueva` |
| Sin conexión (celular) | No hay cola local: sin red no se envía y se avisa; nada se muestra hecho antes de la respuesta | modal de entrega (`RemisionAccionModal`) |
| Fallo externo | Correo: bandeja con reintento, sin fingir entrega. Evidencias: la bitácora fallida revierte la carga | `test_fallo_smtp_no_finge_entrega_y_se_reintenta`, `test_evidencias_privadas` |
| Caída del proceso a mitad de operación | Cada operación es una transacción: si algo falla después de guardar la cabecera, no queda nada a medias | `test_pagar_en_efectivo_sin_saldo_no_deja_cambios` y regresiones de atomicidad |
| Migración interrumpida | En MySQL/MariaDB el DDL no es transaccional: la salida es el respaldo previo. Las migraciones son expansivas y `migrate` repetido no hace nada | Ensayo del 2026-10-06 (abajo) |
| Recuperación de respaldo | Ensayada en local (abajo) | — |

**Ensayo de respaldo (2026-10-06):** el respaldo `pruebasv3_antes_migr_ordenes0044_*.sql.gz`, de la copia en MariaDB 11.8, se restauró en un MySQL 8.4 desechable.
- **Restauración:** menos de 1 s; 82 tablas y 12.564 filas, idénticas a la copia viva. Solo difieren las tablas internas de Django, por las migraciones aplicadas después del respaldo.
- **Migración:** `migrate` aplicó las 7 pendientes en 1 s; repetirlo no hizo nada.
- **Diagnóstico:** `diagnostico_auditoria` corrió sobre la base restaurada.
- **Limpieza:** la base y el servidor temporales se borraron.
- **Pendiente:** repetirlo en el VPS con un respaldo de producción y medir allí el tiempo real (P07-05, D08).

**Excepciones de datos vistas en el diagnóstico** (ya conocidas en P06, no bloquean la migración):
- 24 facturas pagadas sin comprobante;
- 2 ventas con abono descuadrado;
- 3 productos "por despachar" sin remisión activa;
- 4 egresos en efectivo sin movimiento de caja;
- 1 movimiento histórico con saldo negativo. El saldo actual es positivo, así que `ordenes 0037` no se detiene.

**Pendiente con infraestructura:**
- caída real de un worker de gunicorn durante una petición;
- corte de red entre el VPS y la base de Hostinger;
- restauración en el VPS.

## 3. Guiones para la aceptación con operadores (P14-03, pendiente de ejecutar)

Preparar en staging (o en la copia de pruebas) con datos ficticios: un cliente "Cliente Prueba", un proveedor "Proveedor Prueba", una referencia y una zona. Cada persona usa su usuario real y su rol real. Observar en escritorio y en **iPhone** (Safari, con https).

| Función | Pasos | Debe pasar |
|---|---|---|
| Auxiliar (ventas y caja) | Registrar una venta con su precio de lista; cobrar 50 % en efectivo y 50 % en transferencia; hacer el cierre de caja | El efectivo entra a caja; la transferencia queda pendiente; el cierre deja constancia sin cambiar el saldo |
| Administrador (aprobaciones) | Confirmar la transferencia; anular un recibo de prueba con motivo | El saldo de la venta se recalcula; la anulación queda en el historial |
| Auxiliar (compras y bodega) | Crear la orden de pedido; registrar la factura eligiendo la línea; recibir solo una parte; registrar un rechazo | Órdenes muestra "Recibidas x/y" y "Rechazadas"; no deja recibir de más |
| Vendedor | Ver su venta y la compartida; crear la remisión; verificar que no ve costos | No aparecen ventas ajenas ni costos |
| Transportador (iPhone) | Abrir su remisión; "Verificar productos con QR" con la cámara; despachar; confirmar entrega marcando un producto como no entregado | Pide permiso de cámara; lee la etiqueta; un código ajeno avisa; lo no entregado aparece en la siguiente remisión |
| Tesorería | Importar el extracto del mes (vista previa y luego confirmar); conciliar un cobro recomendado | Reimportar el mismo archivo da aviso; conciliar no confirma pagos |
| Cualquiera | Dos pestañas abiertas durante la noche; volver al día siguiente | Ninguna pestaña pide iniciar sesión de nuevo antes de que venza el refresh |

Registrar por cada fila: quién, dispositivo, resultado, problema y captura. Los problemas de accesibilidad (teclado, contraste, botones pequeños en el celular) se corrigen antes de publicar.

## 4. Publicación gradual (P14-04, pendiente de tu autorización)

1. **Requisitos:**
   - completar la "Lista de despliegue" de `operacion.md`: `.env` con `DB_*` y `DJANGO_SECRET_KEY`, respaldo verificado, carpeta privada de evidencias;
   - llevar la rama a `main`. Hoy no hay commits: hay que decidir cómo agrupar los cambios.
2. **Backend primero:** es compatible con el frontend actual. Las facturas sin línea, las remisiones sin "no entregados" y las peticiones sin clave de idempotencia funcionan igual.
   - **Verificar:** `/api/health/`, login y una consulta de ventas.
   - **Si falla:** volver al commit anterior del código. Las tablas nuevas no estorban al código viejo.
3. **Frontend después:** `npm install` (por `jsqr`), `npm run build` y subir `dist/`.
4. **Activación por permisos,** que es el mecanismo de gradualidad: las pantallas nuevas no aparecen hasta asignarlas en Usuarios.
   - **Día 1 (sin cambiar hábitos):** sesiones, idempotencia, recepción ligada a la orden, entrega parcial, historial de inventario.
   - **Semana 1:** prueba de iPhone con el transportador; resolver R1.
   - **Semana 2:** VER_BANCOS/CONCILIAR_BANCOS a quien maneje tesorería; VER_NOMINA/GESTIONAR_NOMINA a quien liquida la nómina.
   - **Después:** Calidad de clientes, cuando se definan responsables.
5. **Señales que vigilar:**
   - 5xx en `journalctl -u gunicorn`;
   - 409 frecuentes (dobles envíos);
   - correos en estado "fallido";
   - quejas de sesión cerrada;
   - diferencias de arqueo.
6. **Vuelta atrás de datos:** solo con el respaldo previo, restaurado primero en una base aparte, según la sección de recuperación de `operacion.md`.

## 5. Cierre (P14-05)

No se puede cerrar hasta publicar y ejecutar §3. Riesgos residuales hoy:
- credenciales expuestas sin rotar (P01-03);
- datos históricos con excepciones (§2, P06-04);
- decisiones abiertas: D02 descuentos y anticipos, D07 duración de la sesión, D08 tiempos de recuperación, D10g programación provisional;
- prueba en iPhone real pendiente;
- nada desplegado.
