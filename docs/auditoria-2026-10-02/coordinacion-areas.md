# Coordinación de áreas y recorridos — P18

Implementación local, 2026-10-09. No publicada. La oficina usa personas, agentes y ventas existentes en **u756180748_pruebasv3**; no se crean usuarios, ventas, tareas humanas ni resultados pedagógicos para una demostración.

## Uso

En `/IA`, **Informe de áreas** abre el informe compartido de gerencia. Oscar y Stiven pueden usar **Pedir informe ahora** o escribir **«dame un informe de las areas»** en una conversación de **IA Lottus general**. También acepta «áreas» con tilde, mayúsculas y espacios adicionales. La misma frase en el chat del Coach u otro perfil conserva ese chat y no inicia al coordinador.

El programa quedó activo: primer recorrido diario a **09:50**, luego actualización de Coach y ventas a **10:50, 11:50, …, 18:50**, hora de Bogotá, todos los días. El cierre y los días son provisionales y editables por Stiven, responsable actual de oficina, en **Informe de áreas → Programa**. Oscar consulta y solicita, sin modificar el programa. Las automatizaciones privadas anteriores siguen separadas del informe compartido.

Coach y analista corresponden a perfiles reales existentes, IDs 3 y 1. Destinatarios: usuarios reales Stiven (5) y Oscar (6), activos e invitados. No se infieren destinatarios por nombre al atender peticiones. Desactivar una cuenta o retirarla de oficina revoca su acceso a informes. Los informes antiguos conservan sus destinatarios; invitar otra persona no le entrega el historial anterior.

## Evidencia del informe

- Coach: cada cuenta activa invitada, estado y presencia fechada, trabajos pendientes/en curso/bloqueados, entregas de hoy y trabajos con fecha objetivo vencida. `entregado_en` se registra al pasar a entregado; los comentarios posteriores no cambian el día de entrega. Las tareas históricas sin ese dato no reciben una fecha inventada.
- Formación: el ERP todavía no registra clases, asistencia ni exámenes. El informe lo declara expresamente. Los conteos de tareas no se presentan como aprendizaje, notas ni porcentaje de capacitación.
- Ventas: todas las ventas visibles pendientes, sin limitar arbitrariamente a un mes; gestión atrasada según `GESTION_DIAS_LIMITE`, entregas con compromiso superado y productos sin confirmar. El total cuenta ventas únicas, mientras cada asesor ve sus participaciones, incluidas compartidas. No se calcula facturación ni se altera la regla monetaria Total/N.
- Plan comercial: acciones por cada venta, responsables vendedor/analista, búsqueda por venta/vendedor y paginación. Pedidos atrasados que aún no están recibidos requieren seguimiento, incluidos los que están `finalizado`. Son propuestas de próximos pasos, no tareas creadas automáticamente ni cambios de venta.
- No existe vencimiento financiero por edad del saldo: el informe habla de atrasos operativos. Los registros históricos pendientes requieren verificar su estado antes de interpretar el atraso como incidencia vigente.
- Comparación con la captura anterior; el latido de presencia no se interpreta como avance de trabajo. La última evidencia está fechada y no afirma conocer cambios posteriores a la captura.

Primera ejecución real de datos ERP: informe #1, **8 personas y 801 ventas pendientes**. Frase de activación probada por HTTP en localhost:8000 y enlazada a un informe real y su respuesta privada. Solo se crearon informes/registro de ejecución y la conversación necesaria para esa comprobación; no se modificaron ventas, tareas ni otras conversaciones.

## Análisis externo y autorización

**Inicialmente `modelo=''`: solo datos ERP. No llama a Gemini ni adjunta el informe a otras consultas generales de Gemini.** Los recorridos y el informe estructurado funcionan en este modo y dicen «revisando indicadores», sin presentar texto preparado localmente como una respuesta del modelo.

La revisión automática de herramientas rechazó la prueba que podía enviar datos internos de empleados/ventas a Gemini porque ese envío no tenía autorización explícita. Se terminó y verificó la alternativa sin envío externo. No se ha probado el proveedor real para este flujo.

Para habilitar el análisis de los líderes se requiere elegir **Gemini automático** o un modelo disponible, marcar **Autorizo enviar esta evidencia a Gemini** y guardar. La API rechaza la primera activación sin `autorizar_envio=true`. El usuario también puede autorizar expresamente esa activación al agente que continúa la implementación.

Payload: nombres/roles/estado/presencia y conteos de trabajo de invitados para el Coach; conteos de ventas por asesor y hasta 20 pendientes prioritarios de proveedores para el analista; instrucciones/documentos del perfil que ya forman parte de su configuración. No adjunta chats privados de empleados, clientes, importes de ventas ni registros de nómina. Las preferencias personales del solicitante no se añaden a las llamadas de análisis compartido. Los destinatarios son los gerentes configurados.

Cada líder usa una llamada acotada, sin herramientas de escritura. El modo automático cambia de modelo si está saturado. Si el proveedor falla, se conserva la evidencia en un **informe parcial** con el error concreto y modelo modificable. Los gráficos y conteos se calculan desde el ERP, no desde texto generado. El presupuesto total del análisis es acotado y el motor marca las interrupciones; nunca repite llamadas automáticamente para «recuperar» una respuesta.

La memoria enviada a la IA general se habilita solo después de autorizar el análisis externo y solo para gerentes destinatarios. Se limita a evidencia fechada; no exporta planes completos ni conversaciones humanas.

## Movimiento y trabajo humano

`InteraccionOficina` registra hechos duraderos de consulta/revisión/entrega y solicitudes humanas. El frontend consume un cursor, deduplica IDs y anima el actor por los pasillos. IA Lottus revisa Entrenamiento, Comercial, otras áreas y entrega a gerencia. Un área sin líder se visita como revisión pendiente, sin conversación ni resultados inventados. El movimiento no ejecuta el trabajo y no mueve permanentemente los puestos.

Durante una misión, el personaje y su interlocutor dejan de hacer paseos ambientales. La conversación se indica con un globo breve, el actor continúa a la siguiente área y vuelve al puesto. «Reducir movimiento» conserva la información sin desplazamientos animados. Al desmontar se limpian los temporizadores; no se reconstruyen como actividad presente recorridos antiguos.

En **Bandeja → Trabajos → Pedir actualización**, una persona invitada elige Oscar o Stiven. Al guardar se registra su visita al gerente. Al marcar **Entregada**, quien realmente registró la entrega visita al creador; si Stiven atiende una solicitud asignada a Oscar, el recorrido muestra a Stiven. Repetir el estado no duplica la visita. Revisiones concurrentes devuelven 409 antes de sobrescribir avances.

El plano solo muestra textos genéricos, nunca título/descripción de una tarea privada, conversación privada, venta ni importe. Las personas ajenas al trabajo no adquieren acceso a sus detalles por ver una animación. Todos los usuarios siguen teniendo únicamente sus permisos previos de IA, oficina y ventas.

## Motor, migración y recuperación

El motor existente `ejecutar_automatizaciones_ia` atiende la cola privada y la compartida con capacidad limitada; está activo localmente con `LOTTUS_LOCAL_TEST_DB=1`. Una pestaña cerrada no detiene los informes. Se mantiene una sola reserva activa, idempotencia por franja/clave manual, entrega única entre workers y recuperación explícita de cola/informes interrumpidos. Al recuperar un motor detenido se prepara una captura actual sin repetir toda la jornada perdida. Máximo 12 solicitudes manuales de informe/hora; el chat mantiene además su límite existente de preguntas.

Migración **0067_coordinacion_areas**, dependiente de 0066 en la rama de oficina. Crear tablas de coordinación/informes/eventos y añadir `entregado_en` nullable a trabajos. Respaldo parcial verificado de las tablas afectadas antes de aplicar, con permisos 0600: `respaldos_locales/pruebasv3_antes_coordinacion_20261009_080609.sql.gz`. Conteos de personas, perfiles, trabajos y chats preservados. **0057 y 0061 no se ejecutaron**.

No ejecutar `migrate` global en pruebasv3: el merge 0061 arrastra la eliminación de Bancos. Destino explícito de esta entrega:

```sh
LOTTUS_LOCAL_TEST_DB=1 testenv/bin/python manage.py migrate ordenes 0067_coordinacion_areas
LOTTUS_LOCAL_TEST_DB=1 testenv/bin/python manage.py ejecutar_automatizaciones_ia --continuo
```

Para una instalación nueva, configurar IDs reales existentes con `configurar_coordinacion_oficina --destinatarios … --coach … --analista … --activar --hora-fin 18:50`. Valida administradores activos invitados y perfiles ubicados correctamente; no inventa identidades. Rechaza sobrescribir un programa existente: editarlo en la interfaz con revisión.

## Verificación y límites

Suite completa SQLite, sintaxis, migraciones, frontend, lint y build registrados en seguimiento. Siete regresiones de concurrencia pasaron en MySQL 8.4 desechable, cerrado al terminar: misma clave, reservas simultáneas, entrega única y escrituras humanas concurrentes. No se usan datos reales en esas bases desechables.

HTTP local: coordinación, informe e interacciones devuelven 200; la frase del chat devuelve 202 y el worker completa el informe. Sesión efímera para comprobar el contrato, sin cambiar contraseñas ni guardar tokens. Vista de solo lectura temporal con **el componente real y captura de datos de pruebasv3**: diseño a 800 px y móvil de 390 × 844, Coach, búsqueda, plan y movimiento de eventos reales. No se inició sesión ni se alteraron preferencias en el navegador; la vista temporal se elimina después de validar. Evidencias: [informe](evidencias/coordinacion-areas-real.jpg), [móvil](evidencias/coordinacion-areas-movil.jpg), [oficina](evidencias/coordinacion-recorrido-real.jpg).

Pendiente de negocio/usuario: autorizar el análisis externo si se desea; definir hora de cierre/días; crear y asignar líderes de Oficina, Desarrollo creativo y Zona social; registrar evidencia de clases/exámenes para medir formación. No hay calificaciones ni acciones humanas ficticias. El informe local ya es utilizable sin esos datos, identificando sus ausencias.
