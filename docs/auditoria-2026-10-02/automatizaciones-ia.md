# Automatizaciones por agente y oficina ampliada — P17-06 a P17-09

Entrega local iniciada el 8 y cerrada el 9 de octubre de 2026. Frontend `localhost:3000`, backend `localhost:8000`, base real de prueba `u756180748_pruebasv3`. No publicada. Complementa [oficina-ia.md](oficina-ia.md).

## Uso

1. En `/IA`, acercar el mouse al puesto de un agente. La ficha indica su actividad real, la próxima tarea en hora de Bogotá y los resultados propios pendientes de leer. Con teclado se abre al enfocar el puesto; flecha abajo entra a la ficha y Escape la cierra. En móvil usar **Actividad** en su tarjeta.
2. Pulsar **Programar tarea** desde la ficha, o **Tareas** en la tarjeta y **Nueva tarea**. **Automatizaciones** en la cabecera reúne las tareas de todos los agentes de ese usuario.
3. Elegir agente, nombre e instrucciones. Las cuatro propuestas iniciales rellenan instrucciones editables; no crean automatizaciones ni documentos por sí solas.
4. Elegir una fecha única, todos los días, días de la semana o un día del mes; hora fija de **America/Bogota**, independiente de la zona del navegador. El día 31 se ajusta al último día de un mes más corto. Fecha límite opcional. Un calendario activo sin ninguna fecha futura se rechaza.
5. Dejar el modelo automático para usar el respaldo existente de Gemini, o seleccionar un modelo concreto. Guardar activa o pausada. La próxima ejecución queda visible en la tarea y en la ficha.
6. **Ejecutar ahora** encola una ejecución manual cuando el motor está activo; no mueve el horario programado. **Pausar** detiene las futuras reservas. Las tareas ya en cola o en ejecución pueden terminar.
7. **Historial** conserva ejecuciones, estados, fechas, errores y modelo realmente usado. Abrir un resultado lo marca como leído y lleva a su conversación privada. El resultado también se conserva si posteriormente se elimina ese chat.
8. **Archivar** retira la tarea del listado normal sin borrar su historial. **Ver archivadas** permite recuperarla; **Restaurar pausada** exige activar después de revisar su calendario. Un perfil pausado/eliminado produce un error visible, nunca una sustitución silenciosa por el general.

Los resultados se entregan dentro de la plataforma. No se envían correos, mensajes ni documentos a terceros, ni se modifican ventas, nómina, caja o inventario. La generación usa el proveedor Gemini ya configurado; cada consulta consume su cuota y puede fallar por disponibilidad del modelo. Las tareas utilizan las áreas y el conocimiento del perfil vigente al iniciar, con las instrucciones y modelo de la tarea guardados al encolarla.

## Áreas y plano

El plano conserva la identidad aprobada (Audiowide blanca sobre negro, madera, vidrio, metal negro, tapizados neutros) y mantiene el contorno horizontal: Comercial ocupa la franja derecha completa (doble superficie) y las otras cinco áreas se distribuyen en dos filas a la izquierda, con navegación horizontal, arrastre de fondo, flechas y zoom entre 60 % y 140 %. Las seis áreas iniciales aparecen juntas; hasta doce zonas personalizadas se recorren en grupos de seis. La capacidad por grupo es siete en Comercial, tres en Gerencia y Social, uno en Entrenamiento y dos en el resto; Equipo conserva el directorio completo.

| Área | Mobiliario propio |
| --- | --- |
| Gerencia | Tres escritorios (dos futuros), archivo ejecutivo, mesa de reunión y cuadro |
| Oficina | Puestos administrativos, archivo, impresora y papelería |
| Área comercial | Siete escritorios: analista IA y seis puestos para vendedores futuros |
| Entrenamiento | Pantalla LOTTUS Academia, escritorio del formador y seis sillas para clases |
| Desarrollo creativo | Muestrario, mesa de dibujo y plano de trabajo |
| Zona social | Cafetera, sofá de tres plazas, tres sillones, mesa y plantas |

Los muebles son ilustraciones, no existencias de inventario. No se añadieron personas ni agentes de ejemplo. La ampliación conserva los identificadores y perfiles de las zonas existentes; las zonas personalizadas también permanecen.

## Motor del servidor

`ejecutar_automatizaciones_ia` es un proceso independiente de Django HTTP y del navegador. Por defecto consulta cada diez segundos y usa dos trabajadores. Una reserva con bloqueo de fila y clave única evita franjas duplicadas; una comparación de estado impide que dos trabajadores consuman la misma ejecución. Chat y automatizaciones serializan la cuota por usuario en la misma fila de usuario.

- Máximo 50 tareas sin archivar y 20 activas por usuario. Cuota compartida de 40 preguntas/ejecuciones por hora. No se ampliaron permisos: crear/editar/ejecutar requiere los existentes `USAR_ASISTENTE_IA` + `GESTIONAR_PERFILES_IA`. La consulta exige uso de IA y conserva propiedad privada por usuario.
- Antes de generar se comprueban usuario activo, permisos actuales y perfil activo. También se revalida el perfil en la entrada a generación para cubrir una eliminación ocurrida entre reserva y respuesta.
- Cada ejecución registra el nombre, instrucciones, modelo solicitado y agente original. Resultados y errores son persistentes. Las listas consultan últimas ejecuciones por lote; no hay una consulta adicional por cada tarea.
- Tras una parada prolongada, se reserva una ejecución atrasada por tarea y se calcula el siguiente horario futuro; no se reproduce cada día perdido. Una tarea de fecha única se desactiva al reservarse.
- Una ejecución en curso durante más de cinco minutos se declara interrumpida. Una cola sin iniciar durante treinta minutos termina como error. No se reintenta automáticamente un resultado incierto ni se vuelve a llamar a Gemini por repetir un intento HTTP. El usuario puede iniciar un intento nuevo.
- La oficina consulta actividad cada diez segundos y el panel cada ocho. **Motor activo** significa que confirmó un latido en los últimos cinco minutos; puede tardar ese tiempo en reflejar una parada. El horario efectivo depende de la cola y la disponibilidad del proveedor, no garantiza ejecución al segundo exacto.

### Local

El motor queda arrancado para pruebasv3. PID del proceso actual en `/tmp/lottus-ia-automatizaciones.pid`, salida en `ordenesPedidoSWBackend/automatizaciones-ia.log`. No se configuró inicio automático al encender el Mac. Si se detiene o reinicia el equipo, abrir una terminal en el backend y ejecutar:

```sh
LOTTUS_LOCAL_TEST_DB=1 testenv/bin/python manage.py ejecutar_automatizaciones_ia --continuo
```

La variable selecciona de forma explícita y fija **pruebasv3**, usando las credenciales locales existentes; no confía en un nombre de base de producción del `.env`. No iniciarlo sin esa variable en este equipo. Evitar arrancar procesos adicionales innecesarios. Ctrl+C detiene el motor de terminal y espera las tareas ya iniciadas. El proceso entregado en segundo plano puede detenerse con SIGINT tras comprobar que el PID del archivo sigue perteneciendo a ese comando.

### Publicación futura

Preparada una plantilla [lottus-automatizaciones-ia.service.example](../../deploy/lottus-automatizaciones-ia.service.example). Ajustar usuario/rutas y usar el entorno de la base destino con permisos adecuados. **No definir `LOTTUS_LOCAL_TEST_DB` en producción.** Instalar y habilitar el servicio solo dentro de un despliegue autorizado; no se hizo en esta entrega.

Antes de publicar: respaldar la base destino, inspeccionar el plan y migrar explícitamente a `ordenes 0064_entrenamiento_oficina_ia`; comprobar que ese plan no incluye eliminaciones ajenas. Luego publicar backend, arrancar el servicio y publicar frontend. No aplicar una migración global que ejecute inadvertidamente el pendiente independiente **0057_eliminar_bancos**. Vigilar el latido y revisar errores de prueba con una tarea real decidida por el operador.

## Migración aplicada en pruebasv3

**0063** depende de **0062_oficina_ia**. Crea `AutomatizacionAsistente`, `EjecucionAutomatizacionIA`, `MotorAutomatizacionesIA` y amplía ambientes. Actualiza configuración de áreas existentes sin borrar perfiles ni conversaciones. Las cuatro zonas iniciales evolucionan a Gerencia, Oficina, Área comercial y Desarrollo creativo; se añade Tecnología y se conserva la Zona social ya creada por el usuario.

Se verificó el plan exacto de una sola migración y se aplicó ese destino. **0057 y el merge 0061 siguen sin aplicar**. El merge 0061, que nunca se aplicó, ahora une 0057 con 0064. No se retiraron tablas de Bancos ni se tocaron datos comerciales.

Respaldo **parcial**, no completo: `respaldos_locales/pruebasv3_ia_antes_programacion_20261008_233631.sql.gz`, con zonas, perfiles y registro de migraciones; permisos 0600, terminación del dump y descompresión verificadas. Después de migrar se comprobó que los conteos de perfiles y conversaciones se conservaran. No se sembraron automatizaciones ni resultados de ejemplo en esta base.

Una reversión de código puede detener el servicio y dejar tablas/configuración para conservar historial. La reversión de esquema perdería tareas y ejecuciones y necesita respaldo y revisión específica. La reversión de datos de las zonas no es automática; no asumir que desmigrar devuelve sus nombres anteriores.

## API

Todas las rutas bajo `/api/asistente/`, autenticadas y privadas por responsable:

| Ruta | Operación |
| --- | --- |
| `oficina-actividad/` | GET tareas, próximas ejecuciones, trabajo y novedades sin leer |
| `automatizaciones/` | GET filtradas por `perfil=general` o ID; `archivadas=1` incluye archivadas. POST crear con idempotencia |
| `automatizaciones/<id>/` | GET detalle, PATCH editar/pausar/archivar/restaurar |
| `automatizaciones/<id>/ejecutar/` | POST con `Idempotency-Key` válida; devuelve 202 con reserva persistente |
| `automatizaciones/<id>/ejecuciones/` | GET historial, `offset` en bloques de 30 |
| `ejecuciones/<id>/` | GET resultado completo; PATCH `{leida: true}` |

Una clave de ejecución manual repetida recupera la misma ejecución, incluso terminada. Otro intento mientras esté en cola/trabajando devuelve 409. No hay eliminación irreversible de tareas desde esta API.

## Verificación y límites de la evidencia

Backend: **359 pruebas descubiertas en SQLite; 345 correctas y 14 omitidas que requieren MySQL**. En MySQL 8.4 desechable, sin red y sin datos reales, **las 14 pruebas de concurrencia fueron correctas**, incluidas cinco nuevas de reservas, reintentos, dos trabajadores, cuota entre tareas y cuota compartida con chat. Veinte regresiones de automatizaciones comprueban calendario, permisos/propiedad, idempotencia, interrupciones, límites, resultados, archivo y perfil desaparecido. Gemini se simula solo en estas pruebas aisladas; no se simulan respuestas de la plataforma.

Frontend: **166/166 en 33 archivos**, diez nuevas; lint con cero errores y veinte advertencias previas. Después de los ajustes finales de capas, movimiento reducido, foco y altura de fichas se repitió `npm run check`: 166/166, lint cero errores/veinte avisos previos y build correcto. Sintaxis Python y generación de migraciones verificadas.

Navegador con datos reales: las seis áreas, zoom, desplazamiento, ficha con mouse/teclado, motor activo, selección de agente/modelo y formulario semanal/mensual/de una fecha sin guardar una tarea ficticia; vista móvil de 390 × 844 y restauración del viewport. Evidencias en `evidencias/oficina-ia-automatizaciones*.png`, `oficina-ia-ficha.png`, `oficina-ia-programar.png`, `oficina-ia-ampliada-movil.png`.

La generación automática y conservación de resultados se validaron con proveedor simulado en bases aisladas. No se ejecutó una tarea nueva con Gemini real ni se publicaron estos cambios; el primer horario real y su aceptación los define el usuario desde la interfaz.


## Actualización de oficina y chat — 2026-10-09

Entrenamiento reemplaza a Tecnología mediante 0064, aplicada sola en pruebasv3 tras el respaldo parcial verificado `pruebasv3_ia_antes_entrenamiento_20261009_001803.sql.gz` (zonas, perfiles y migraciones; no es un respaldo completo). Se conserva el ID de zona y la vinculación de perfiles e historial. 0057 y 0061 siguen pendientes.

El chat y los resultados ahora se abren dentro de la oficina; Ampliar ofrece la pantalla completa. Calendarios, permisos y motor conservan su comportamiento. La nueva distribución incluye siete escritorios comerciales y tres de Gerencia, aula y zona social equipada; ver [oficina-ia.md](oficina-ia.md). La formación semanal puede configurarse posteriormente como tarea del perfil que cree el usuario, sin que eso añada un sistema de exámenes interactivos ni usuarios humanos.

Validación de esta revisión: 169 frontend; lint cero errores/veinte avisos previos y build; 347 correctas y 14 omitidas de 361 backend SQLite; sintaxis/migraciones correctas. Capturas de plano, chat integrado y móvil en la guía de oficina. Los resultados P17-09 anteriores conservan su fecha y alcance.
