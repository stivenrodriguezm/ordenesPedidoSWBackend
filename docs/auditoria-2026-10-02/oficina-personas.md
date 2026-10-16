# Personas y colaboración en la oficina virtual — P17-14 a P17-17

**Ampliación P18 (2026-10-09):** las solicitudes permiten elegir Oscar o Stiven y generan una visita a gerencia. Al entregar, quien marca el trabajo visita a su creador, sin exponer contenido privado en el plano. El informe compartido usa el avance real de los invitados. Véase [coordinacion-areas.md](coordinacion-areas.md).

Actualización del 9 de octubre de 2026. Esta funcionalidad usa las cuentas activas que ya existen en el ERP. No crea usuarios, perfiles de IA, mensajes, tareas ni ventas de ejemplo.

## Qué quedó disponible

- `/IA` conserva la oficina sin la barra superior general. El menú móvil, el enlace a Mi perfil y el menú lateral siguen accesibles.
- El responsable puede abrir «Elegir personas de la oficina», buscar usuarios activos y marcar de forma explícita quién participa. Puede dejar a alguien sin puesto o asignarle una zona y un puesto libre. La selección usa revisión optimista y no permite duplicar un asiento.
- Una persona invitada entra a la oficina con su cuenta real, pero conserva exactamente sus permisos actuales. La invitación no concede IA, ventas, precios ni acceso a conversaciones ajenas.
- Cada persona tiene estado disponible, ocupado o ausente, una nota breve y presencia efímera. El indicador «en oficina» se basa en un latido visible de 45 segundos y caduca después de dos minutos sin actividad.
- «Bandeja» ofrece mensajes del equipo, conversaciones privadas entre participantes, destacados con caducidad, tareas, solicitudes al responsable, comentarios, estados y un resumen de ventas limitado por los permisos que ya tenía la persona.
- Un destacado público muestra una burbuja entre comillas sobre el puesto y solo puede existir uno activo por autor. Los mensajes privados nunca se muestran como destacados públicos y el responsable no puede leer una conversación privada en la que no participa.
- Las tareas no mutan ventas, pedidos, facturas ni remisiones. Una venta solo se vincula si ambas personas pueden verla; la información financiera no se copia a la bandeja.
- Los pasillos de la planta SVG son más anchos. Se mantienen siete puestos en Área comercial, tres en Gerencia, un puesto en Entrenamiento y tres asientos en Zona social. Todavía no hay movimiento de personajes.

## Cómo usarlo

1. Entra a `/IA` con una cuenta administradora.
2. Pulsa «Elegir personas de la oficina». Marca solo las cuentas que realmente deban participar, elige zona/puesto y guarda.
3. El primer guardado fija al usuario actual como responsable. Después, solo ese responsable puede cambiar la selección, retirar participantes o reasignar tareas.
4. Abre «Bandeja» para escribir al equipo, seleccionar una persona, crear una tarea, pedir una actualización o revisar el resumen de ventas. La opción «Destacar en la oficina» permite elegir 1, 4 o 24 horas.
5. La persona invitada debe recargar su sesión o volver a entrar para que el menú y la ruta `/IA` reconozcan el acceso nuevo. Retirarla conserva el historial, pero bloquea nuevas operaciones de oficina para esa cuenta.

## Límites deliberados

La propiedad de la oficina no se transfiere desde la interfaz. Si el responsable queda inactivo, el acceso de coordinación queda bloqueado hasta que se recupere esa cuenta; esto protege la regla de que solo el propietario elegido pueda gestionar personas. Tampoco se envían notificaciones externas, correos o mensajes a nombre de un usuario. Las solicitudes quedan registradas para que el responsable las atienda manualmente.

Los puestos representan una ubicación visual, no una reserva de inventario. Los datos del resumen comercial son contadores y referencias de venta permitidas; no reemplazan Ventas ni Nómina. Los estados y destacados son informativos y tienen límites de frecuencia para evitar que una cuenta llene la oficina.

## Contrato técnico y datos

La migración `ordenes 0065_personas_oficina` crea `ConfiguracionOficina`, `MiembroOficina`, `MensajeOficina`, `TrabajoOficina` y `ComentarioTrabajoOficina`. La migración fue aplicada únicamente en la base de pruebasv3 después de un respaldo parcial verificado:

`respaldos_locales/pruebasv3_antes_oficina_personas_20261009_004352.sql.gz`

Las rutas están bajo `/api/oficina/`: `estado`, `equipo`, `presencia`, `mensajes`, `mensajes/leer`, `trabajos`, `trabajos/<id>`, `trabajos/<id>/comentarios` y `personas/<usuario>/ventas`. Las respuestas no incluyen correo, credenciales ni campos privados innecesarios. Las escrituras vuelven a comprobar usuario activo, pertenencia, responsable, revisión y visibilidad de venta dentro de la transacción.

La eliminación de `0057_eliminar_bancos` continúa fuera de esta entrega y no se ejecutó. No se publicó el cambio.

## Verificación

La suite backend terminó con 375 pruebas correctas en SQLite y 18 omitidas por requerir MySQL. Las diez pruebas de personas pasaron; las cuatro pruebas concurrentes en el MySQL desechable pasaron: dos selecciones con la misma revisión producen una sola aceptación, dos destacados dejan uno activo, dos cambios de tarea no pierden la revisión y retirar una persona bloquea una escritura que estaba esperando.

Frontend: 183 pruebas correctas en 34 suites, lint sin errores (20 advertencias existentes) y build Vite correcto. La revisión de navegador usó los datos actuales de pruebasv3: se visualizaron cuentas reales en el editor, el mapa con personas ubicadas, el acceso a la bandeja y los pasillos ampliados. Evidencias: [mapa y pasillos](evidencias/oficina-personas-pasillos.png) y [gestión de personas](evidencias/oficina-personas-gestion.png).

El backend de desarrollo debe ejecutarse con la configuración local de pruebas en `localhost:8000` y el frontend en `localhost:3000`. Si el backend no responde, la UI muestra «No se pudo cargar la oficina» y un botón de reintento; no presenta datos ficticios.
