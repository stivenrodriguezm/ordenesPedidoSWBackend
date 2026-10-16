# Oficina: movimiento, colaboración y fichas de actividad

Implementado el 9 de octubre de 2026 en frontend y backend de localhost.

- Todas las respuestas y automatizaciones registran inicio en el puesto, consultas de áreas y entrega al solicitante. Aplica a tareas creadas por la interfaz, manuales y programadas. Los errores producen una visita de revisión, no una entrega de éxito.
- Los agentes pueden consultar el criterio de otro perfil activo visible y abrir una pregunta privada a su administrador. Las consultas a colegas usan Gemini sin herramientas recursivas; como máximo dos por respuesta. Una visita por colega en cada conversación. El estado público usa avisos genéricos; preguntas, resultados y automatizaciones conservan su propiedad privada.
- El motor propone una iniciativa por minuto, solo ante administradores presentes: máximo una al día por agente y destinatario, y nunca duplica preguntas sin responder. El diálogo se abre en el chat existente. No consume Gemini hasta que el humano responde o programa trabajo.
- Paseos estratégicos según las áreas del agente, con preferencia por el escritorio, máximo dos paseos simultáneos y tres minutos antes de repetir. Las personas ausentes no pasean. Los paseos son ambientación; las consultas y entregas provienen de eventos reales.
- Paso común de 42 unidades por segundo (antes los recorridos usaban 155); pausas de trabajo de 8 s, análisis de 12 s y conversación/entrega de 10 s. Cola independiente por personaje. Un nuevo lote no reinicia los recorridos; una misión retoma la posición interpolada del paseo. Quien recibe una visita espera donde está y vuelve caminando a su puesto al terminar. Respeta movimiento reducido y el montaje de comprobación de React StrictMode. Los eventos de puestos de otra página esperan a que el puesto sea visible.
- Fichas de IA: identidad, objetivo extraído de las instrucciones, ubicación, áreas, trabajo actual, cursos en preparación, indicadores, próxima tarea, lista de automatizaciones, últimas ejecuciones, resultados y orientación pendiente. Fichas de personas: presencia, nota de estado, ubicación y puesto, mensajes, prioridades y trabajos autorizados. Teclado, pantalla pequeña y contenido desplazable.
- Motor local con bloqueo de archivo para impedir dos procesos simultáneos. Se mantiene activo con `testenv/bin/python manage.py ejecutar_automatizaciones_ia --continuo --intervalo 10`.

## Migración

Se aplicó únicamente `ordenes.0071_interacciones_agentes` tras comprobar el plan exacto. Añade referencias opcionales a ejecución y conversación en los eventos. El merge pendiente 0061 pasa a depender de 0071; la rama pendiente 0057 de bancos no se aplicó. No ejecutar una migración general sin revisar el plan.

## Verificación

- Frontend: 221 pruebas aprobadas, 42 archivos; compilación y ESLint de los archivos cambiados. La ficha flotante se verificó dentro del alto visible de la pantalla y permite desplazarse para acceder a todas sus acciones.
- Backend: 106 pruebas en SQLite aislado, 94 aprobadas y 12 de concurrencia omitidas porque requieren MySQL. Incluye ambos orígenes de ejecución, eventos sin duplicados, privacidad, iniciativas y consulta a un colega real simulando el proveedor.
- Chrome: tarea «Prueba de recorridos y colaboración» creada en la misma interfaz que utiliza el usuario, sin horario activo. Ejecución ID 3 terminada `listo`; el analista consultó realmente al coach mediante `consultar_agente_oficina`, preparó tres recomendaciones y registró la entrega a Stiven. Se observó el trabajo animado y el aviso de entrega en el plano. La tarea de prueba se archivó conservando su conversación y resultado.
- Se comprobó en Chrome la ficha del analista con objetivo, tareas, resultado y orientación. Capturas en `evidencias/oficina-*.jpg`.
