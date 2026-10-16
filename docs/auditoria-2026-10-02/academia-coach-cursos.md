# Academia LOTTUS · cursos creados por el coach

Integración local entre `ordenesPedidoSW` (3000) y `ordenesPedidoSWBackend` (8000), 9 de octubre de 2026.

## Uso

En la oficina, abrir **Academia**, conectar Google y elegir **Crear un curso**. El formulario permite indicar objetivo, público, 2–6 módulos, videos y enlaces HTTPS de referencia. El coach también puede investigar referencias públicas. Las ideas sugeridas rellenan el formulario; no son cursos de demostración.

También se puede pedir al **Coach de asesores**: «Crea un curso de manejo de objeciones, en dos módulos, con fuentes y videos». La respuesta ofrece un enlace al curso. El aula contiene lecciones, referencias de las citas, ejercicios, evaluación con retroalimentación, reproducción de videos y descarga de la guía en Markdown.

**Programar para después** abre las automatizaciones existentes con el coach y las instrucciones del curso ya seleccionados. Se eligen allí fecha, hora y recurrencia; para cursos nuevos se propone una sola ejecución. No se creó ninguna programación recurrente como parte de la prueba.

Cada curso es privado de quien lo solicita. No existe asignación al equipo ni publicación automática. El administrador puede habilitar **Academia y cursos** en las áreas de un agente. Se habilitó el Coach de asesores existente (ID 3), conservando sus demás instrucciones y áreas.

## Google y autonomía

Se usa `notebooklm-py[cookies]==0.8.4`, conector **no oficial** basado en la sesión web de Google, en un entorno Python 3.12 separado del Python 3.9 de Django. La conexión puede vencer o cambiar si Google modifica su servicio. Los límites de videos y de uso los aplica la cuenta de Google; Pro no equivale a generación ilimitada.

La conexión rápida a Chrome está limitada al usuario configurado en `ACADEMIA_CHROME_USUARIO_ID`, rol administrador, `DEBUG=True` y solicitudes desde loopback. Para esta instalación se configuró al usuario Stiven (ID 5), después de su autorización explícita para guardar la sesión y crear el curso de prueba con hasta dos videos.

Las cookies no están en la base ni en las respuestas de API. Se guardan en `private_media/academia/sesiones/<usuario>/storage_state.json`, archivo 0600 en directorios privados, excluido de Git. El botón Desconectar elimina la sesión local de la plataforma y conserva los cuadernos de Google. La conexión exige indicar el correo de la cuenta abierta en Chrome y verifica la identidad devuelta por Google. Los nuevos cuadernos conservan la cuenta creadora; cambiar la conexión detiene sus operaciones antes de enviar material a otra cuenta. Otra cuenta requiere su propia sesión, conectada por su propietario; nunca reutilizar la sesión de Stiven para Oscar u otro usuario.

Solo se envían la solicitud original del humano y las fuentes que indicó o autorizó investigar. Las consultas financieras, el historial del chat, las memorias y los documentos internos del perfil no se exportan al cuaderno. El servidor verifica permiso, agente activo y visibilidad antes de cada paso. Las referencias investigadas que Google no logra leer se omiten; el curso utiliza únicamente fuentes confirmadas como legibles. No se marca un video disponible antes de completar su descarga y renombrar el archivo temporal.

## Motor y recuperación

El motor de cursos se inició en esta sesión y continúa aunque se cierre la página:

```sh
testenv/bin/python manage.py ejecutar_academia_ia --continuo
```

Para horarios recurrentes debe estar activo también el motor existente de automatizaciones:

```sh
testenv/bin/python manage.py ejecutar_automatizaciones_ia --continuo
```

Mantener estos procesos bajo el supervisor del servidor cuando se quiera disponibilidad permanente; no dependen de una pestaña abierta. La academia muestra si su motor deja de emitir latidos. Las consultas de progreso usan un contador separado (60/min por usuario); las acciones permiten 10/min. El sondeo no consume el contador diario de la oficina. Durante la prueba se reinició exclusivamente el contador diario de Stiven que ya se había agotado. `--continuo` tiene un bloqueo de instancia local y reservas en BD; cada cuenta procesa como máximo una operación simultánea.

Los identificadores del cuaderno, investigación, fuentes y videos se guardan por pasos. Se reconcilian cuadernos por título único y fuentes por URL. Antes de solicitar un video se guarda un checkpoint. Si Google no confirma su identificador, la plataforma exige vincular el video existente desde el cuaderno o terminar sin videos; no vuelve a solicitarlo a ciegas. Una operación ya iniciada en Google puede continuar aunque se detenga la preparación local.

Los fallos conservan el material y muestran **Retomar preparación** / **Terminar sin videos**. La sesión vencida solicita reconexión. Las escrituras idempotentes de checkpoints pueden reintentarse al reconectar la BD, sin repetir llamadas a Google. Se libera la conexión a MySQL mientras Google trabaja para evitar cierres por inactividad.

## Instalación y migración

```sh
uv venv --python 3.12 .cache/notebook-runtime
uv pip install --python .cache/notebook-runtime/bin/python -r requirements-academia.txt
```

`ACADEMIA_PYTHON` puede señalar otro intérprete con esas dependencias. El runtime debe estar instalado para que la conexión funcione.

Se aplicó **solo** `ordenes.0070_academia_cursos`, después de comprobar que el plan contenía exclusivamente esa migración, en la base `u756180748_pruebasv3` utilizada por el backend local. Añade las tablas `ConexionAcademia` y `CursoAcademia`; no modifica datos operativos previos. Las migraciones pendientes de bancos y su merge no se ejecutaron. No usar un `migrate` general sin revisar esas ramas. El merge pendiente 0061 se ajustó para depender de 0070, continuando la rama existente.

Antes de habilitar el coach se guardó una copia privada de sus áreas en `.cache/academia-perfiles-antes-20261009.json`. No contiene credenciales y está excluida de Git.

## Validación

- Backend: 61 pruebas ejecutadas entre Academia, chat, perfiles, automatizaciones y analítica: 56 aprobadas y 5 omitidas por requerir concurrencia en MySQL (la prueba usa SQLite). Las 12 pruebas de Academia cubren cursos personales, límites de solicitudes y sondeo, idempotencia, petición desde chat, flujo por pasos, cambio de cuenta, agente pausado, fuente opcional no disponible, video ambiguo y recuperación de checkpoints. Gemini y Google se simulan en la BD SQLite aislada; las pruebas no usan la cuenta real.
- Frontend: consentimiento visible, reintento sin duplicados, programación con instrucciones y evaluación interactiva. Suite completa: 214 pruebas, incluida la expectativa actualizada de la plantilla del coach.
- Lint de archivos afectados y compilación de producción.
- Prueba real autorizada desde Chrome: conexión personal, solicitud desde el chat del coach, cuaderno real, investigación y lecciones; las evidencias guardadas en `evidencias/academia-*.jpg` muestran el recorrido. Curso ID 1: 9 fuentes legibles, 2 lecciones con 23/27 referencias reales y 3 preguntas por módulo. Evaluación verificada en móvil (3/3) y diseño sin desbordamiento a 390×844. La conexión inicial no confirmó el correo y se pidió un video; posteriormente Google negó el acceso a ese cuaderno desde la cuenta Pro activa. Esto indica que la selección inicial de sesión no correspondía a la cuenta que debía utilizarse. No se descargó ni se verificó reproducción de ese video y no se solicitó el segundo. Se corrigió la conexión con selección explícita de correo y se verificó muebleslottus@gmail.com; el aula informa el problema de cuenta y conserva las lecciones.

  Con autorización posterior del usuario se creó el curso ID 2 en `muebleslottus@gmail.com`, en el cuaderno `7486a488-c6d7-4ea1-b56a-a7c0f36c17f9`: «Manejo Efectivo de Objeciones de Precio en Muebles Lottus». Terminó con estado `listo` y avance 100%, 10 fuentes, dos lecciones y evaluaciones, y dos videos descargados. Se verificó reproducción real en Chrome dentro de la Academia: primer video de 435,68 s y segundo de 439,44 s, ambos con `readyState=4`, `paused=false` y tiempo de reproducción avanzando. Evidencias: `academia-video-1.jpg` y `academia-video-2.jpg`. No se solicitaron videos adicionales para esta comprobación.
