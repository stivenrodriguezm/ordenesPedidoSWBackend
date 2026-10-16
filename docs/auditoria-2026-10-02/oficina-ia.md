# Oficina virtual IA de LOTTUS — P17

**Ampliación P18 (2026-10-09):** coordinación diaria y horaria de áreas, informes compartidos para Oscar y Stiven, activación por frase en chat general y visitas animadas en solicitudes/entregas. Activo con datos ERP; análisis de Gemini pendiente de autorización explícita. Uso, fuentes, permisos y pendientes en [coordinacion-areas.md](coordinacion-areas.md).

Entrega local del 8 de octubre de 2026. ERP `localhost:3000`, API `localhost:8000`, base real `u756180748_pruebasv3`. No publicada.

**Actualización P17-10 a P17-17 (2026-10-09):** Comercial tiene el doble de superficie de cada otra área y siete escritorios; Gerencia tiene tres. La planta mantiene su ancho anterior. Zona social: cafetera, sofá de tres plazas y tres sillones. Tecnología pasó a Entrenamiento, con pantalla LOTTUS Academia, escritorio y seis asientos para clases futuras. El chat se abre en un panel integrado y se amplía solo por elección. La nueva bandeja de personas permite seleccionar cuentas activas reales, conversar, destacar avisos, asignar tareas y pedir actualizaciones; no concede permisos de IA ni de ventas. `/IA` no usa el Header general y los pasillos son más anchos. La migración 0064 y `0065_personas_oficina` están aplicadas solo en pruebasv3, cada una con su respaldo. Detalle de permisos y operación: [oficina-personas.md](oficina-personas.md). Evidencia: [plano compacto](evidencias/oficina-ia-comercial.png), [chat integrado](evidencias/oficina-ia-chat-integrado.png), [chat móvil](evidencias/oficina-ia-chat-integrado-movil.png), [personas y pasillos](evidencias/oficina-personas-pasillos.png), [gestión de personas](evidencias/oficina-personas-gestion.png).

**Entrega anterior P17-06 a P17-09:** plano ampliado a las seis áreas solicitadas, fichas de actividad al acercar/enfocar el agente y automatizaciones personales persistentes. Motor activo en local, migración 0063 aplicada y pruebas de concurrencia correctas. Recorrido, horarios, API, respaldo, límites y operación en [automatizaciones-ia.md](automatizaciones-ia.md). Las verificaciones de P17-04/P17-05 más abajo corresponden a sus entregas anteriores.

## Revisión de identidad LOTTUS — P17-05

La primera versión de la escena no satisfizo el estilo solicitado. El rediseño usa como referencia visual [muebleslottus.com](https://muebleslottus.com), revisada directamente en navegador, y la definición de marca del usuario: **LOTTUS en mayúsculas, Audiowide regular 400, blanco sobre negro**. Se aplica a la cabecera de la oficina, al letrero de la pared y al logo del menú, incluida su versión colapsada.

La dirección visual es un estudio/showroom de mobiliario: porcelanato, listones y superficies de madera, estructura metálica negra, vidrio, tapizados claros, textiles y pequeños acentos dorados. La escena sigue siendo una ilustración isométrica original en SVG, con materiales, sombras, costuras y mobiliario específico por ambiente. Los personajes tienen proporciones más discretas, vestuario neutro y un pequeño distintivo con el color de su perfil. Ningún mueble ilustrado representa una existencia de inventario ni un producto comercial añadido a la base.

Cabecera, filtros, botones y tarjetas comparten negro, blanco y tonos cálidos, bordes sobrios y jerarquía compacta. Se conserva el directorio legible en móvil y el plano explorable horizontalmente. La etiqueta del selector de zona permanece accesible sin duplicarse visualmente. Los filtros anuncian selección y los controles de grupos de zonas tienen nombre accesible.

Verificación de esta revisión: **156/156 pruebas frontend en 32 archivos**, lint sin errores (20 advertencias existentes) y build correcto. Comprobados en navegador con los perfiles y las zonas reales: puesto del agente, conversación reciente, historial general, filtros y segundo grupo de zonas; móvil de **390 × 844**, sin desbordamiento horizontal de la página. No se enviaron preguntas nuevas a Gemini para comprobar un cambio visual. No se editó backend, ni se migraron o modificaron registros de negocio. Las pruebas backend de P17-04 corresponden a la entrega funcional anterior y no se repitieron en esta revisión visual.

Evidencia actual: [oficina-ia-lottus.png](evidencias/oficina-ia-lottus.png), [oficina-ia-lottus-movil.png](evidencias/oficina-ia-lottus-movil.png). Las capturas anteriores se conservan como registro de la primera entrega.

## Recorrido

- **IA Lottus** en el menú abre `http://localhost:3000/#/IA`. La antigua `/#/chat` redirige a la oficina y conserva las conversaciones existentes.
- La escena isométrica es SVG original: maderas, sofás, plantas, escritorios y monitores en Gerencia, Oficina, Área comercial, Entrenamiento, Desarrollo creativo y Zona social. Cada persona corresponde a un perfil activo de IA; el asistente general es el existente IA Lottus. No se inventaron empleados, agentes, ventas ni productos.
- Clic en una persona o tarjeta abre el chat de ese perfil en un panel lateral sobre la oficina y continúa su conversación más reciente. El selector permite cambiar de agente; cada uno conserva su borrador mientras permanece abierta la página. Cerrar con la X o Escape devuelve el foco a la oficina. «Ver conversaciones» abre el historial del panel; Escape cierra primero ese historial. El botón Ampliar lleva a la pantalla completa con la conversación y el borrador actuales. En móvil el panel ocupa el espacio disponible debajo de la cabecera. Las transiciones respetan movimiento reducido. «Nueva conversación» inicia otra con el mismo perfil. El historial del agente se filtra en el servidor **antes** de limitar/paginar resultados.
- **Chat general**, siempre visible, reúne las conversaciones del usuario con todos los perfiles y con el asistente general. Conserva modelos, aprendizaje, documentos, tablas y gráficos. El historial sigue siendo privado por usuario; general no significa acceder a conversaciones de otras personas.
- **Oficina / Equipo** cambia la representación. Búsqueda por nombre/rol y filtros por zona. En pantallas pequeñas se abre Equipo; el plano sigue disponible con desplazamiento horizontal e indicación para explorar. Los personajes son botones y funcionan con teclado; se respeta la preferencia de movimiento reducido.
- La oficina permite hasta doce zonas, en grupos visuales de seis. Comercial tiene siete puestos, Gerencia tres, Entrenamiento uno, Zona social tres asientos y el resto dos por grupo; «Más puestos» recorre los agentes adicionales sin ocultarlos del directorio. Zonas con menos agentes mantienen sus personas al cambiar el grupo de puestos. Arrastre de fondo, flechas y zoom permiten explorar horizontalmente. En móvil el plano se abre al 60 %; se conserva Equipo como vista inicial.
- Acercar/enfocar un puesto abre su ficha de trabajo, próximo horario y resultados sin leer. Desde ella se puede conversar o programar. Actividad y Tareas en las tarjetas permiten el mismo acceso sin mouse. Las tareas son privadas por usuario aunque utilicen un perfil compartido.

## Gestionar agentes y zonas

Requiere los permisos existentes `USAR_ASISTENTE_IA` y `GESTIONAR_PERFILES_IA`. No se ampliaron roles ni permisos.

1. «Gestionar agentes» abre `/IA/configuracion`. Se reutiliza el editor de perfiles existente: nombre, rol, color, icono, instrucciones, áreas, documentos y disponibilidad.
2. «Crear agente» abre un perfil nuevo. Elegir una plantilla es opcional. Seleccionar su **Zona en la oficina**. Al crear desde una zona vacía se preselecciona esa zona; en creación general se propone el ambiente de estudio si existe, o la primera zona disponible. El usuario puede cambiarla.
3. Las tarjetas permiten reubicar perfiles con un selector de zona; se guarda en el servidor. «Sin zona asignada» conserva el agente en Equipo, accesible para chatear, sin asignarle un puesto ficticio.
4. Al pie de la oficina, «Nueva zona» o el nombre de una zona abre su editor. El ambiente elige muebles de las seis áreas nuevas y conserva las opciones anteriores de estudio, showroom, operaciones y finanzas. Nombre y descripción permanecen editables. Los errores de validación/red se muestran con reintento; el guardado no congela la página.
5. Desactivar un perfil lo retira de la oficina. El historial existente se conserva. En un chat de agente no se cambia silenciosamente al general si el perfil desaparece.

**Usuarios humanos:** la selección es explícita desde `/IA` y usa `CustomUser` activo; no se reutiliza `PerfilAsistente`. La operación, privacidad, límites y recuperación están en [oficina-personas.md](oficina-personas.md).

## Actividad e historial

`GET /api/asistente/conversaciones/` añade `activa` calculada con `Exists`: un mensaje en estado procesando creado en los últimos cinco minutos. Las conversaciones activas se priorizan, aunque fueran antiguas. `perfil=<id>` filtra por agente; `perfil=general` consulta exclusivamente el asistente general; sin ese parámetro se reúnen todos los perfiles del usuario. `offset` pagina en bloques de cien.

La oficina y el historial consultan actividad cada diez segundos. «Preparando respuesta» representa trabajo real del servidor, no presencia humana ni conexión con Gemini garantizada. Los mensajes caducados se siguen recuperando/tratando como error con el mecanismo existente. Un error de actividad no se sustituye por agentes o conversaciones de ejemplo.

El resumen del perfil ahora incluye `activo` y `zona`. Se corrigió el bloqueo tras una primera respuesta: el chat combina el resumen con el perfil cargado y no trata un campo ausente en resúmenes antiguos como una pausa real. Regresión de dos preguntas consecutivas incluida.

## Datos, migración y respaldo

- `ZonaOficinaIA`: nombre, descripción, ambiente y orden. `PerfilAsistente.zona` es FK opcional con `SET_NULL`.
- Migración **ordenes 0062_oficina_ia**, dependiente de **0060_nomina_cierre_por_asesor**. Crea cuatro zonas de configuración y ubica perfiles ya existentes según sus áreas. No crea perfiles nuevos ni transforma documentos comerciales.
- En pruebasv3 se verificó que el plan fuera exactamente 0062 hacia adelante y se aplicó solo ese destino. **0057_eliminar_bancos no se ejecutó**.
- Respaldo **parcial**, no completo: perfiles y registro de migraciones en `respaldos_locales/pruebasv3_perfiles_antes_oficina_20261008_223235.sql.gz`, permisos 0600, descompresión y terminación del dump verificadas. Los intentos iniciales se detuvieron antes de migrar por incompatibilidad de estadísticas del cliente MySQL con MariaDB; se corrigió con `--column-statistics=0`.
- Después de ampliar la oficina se aplicó solo **0063_automatizaciones_oficina_ia**; respaldo parcial, preservación de zonas/perfiles y verificación en [automatizaciones-ia.md](automatizaciones-ia.md). **0064_entrenamiento_oficina_ia** cambia el ambiente y nombre de Tecnología manteniendo el ID; conserva nombres y descripciones personalizados. Su respaldo parcial verificado contiene zonas, perfiles y registro de migraciones: `respaldos_locales/pruebasv3_ia_antes_entrenamiento_20261009_001803.sql.gz`, permisos 0600. `0061_merge_bancos_y_nomina`, nunca aplicada, ahora depende de 0064 y conserva la rama de 0057. Antes de publicar, inspeccionar el plan de migración de la base destino y aplicar las dependencias requeridas con destino explícito. **No usar una migración global para resolver inadvertidamente el pendiente de Bancos.** La autorización/revisión pendiente de P16-02 es independiente.
- Ante reversión de código, los campos/tablas nuevos pueden permanecer para conservar la configuración. Una reversión de esquema eliminaría ubicaciones/zonas; requiere respaldo y revisión específica. No afecta dinero, inventario ni ventas.

## Archivos principales

Frontend: `OficinaIAPage.jsx/.css`, `components/oficina/EscenaOficina.jsx`, `ConfiguracionIAPage.jsx`, `ChatAgentePage.jsx`, `ChatGeneralPage.jsx`; integración en `App.jsx`, Sidebar, Header, ChatPage y PerfilesIA. El ajuste responsive en `index.css` evita que la preferencia de menú colapsado reserve espacio lateral en móvil. Altura del chat ajustada al contenedor real para mantener la entrada visible.

Backend: `ordenes/models.py`, `ordenes/asistente/views.py`, `ordenes/asistente/perfiles.py`, `ordenes/urls.py`, `ordenes/migrations/0062_oficina_ia.py` y dependencia de 0061. El mapa de navegación que recibe la IA usa las rutas nuevas.

## Verificación de la primera entrega — P17-01 a P17-04

Las regresiones se ejecutan en bases aisladas y no insertan sus fixtures en pruebasv3. Cuatro nuevas pruebas API: lectura/administración/ubicación por permisos; validación y límite de zonas; historial personal/general/agente con actividad; paginación de más de cien conversaciones con prioridad de trabajo activo. Doce regresiones UI nuevas entre oficina, chat y editor de perfiles: rutas, búsqueda/vistas, permisos, ubicación/diálogo de zonas, carga fallida, agentes adicionales, perfil desaparecido, conversación ajena, continuidad tras la primera respuesta y zona conservada al usar una plantilla.

Recorrido de navegador con perfiles y conversaciones reales: oficina, puesto del Analista de ventas, su historial, modelos, configuración, editor de zona sin guardar cambios y redirección antigua. Se comprobó el estado de trabajo activo al salir del chat y la recuperación posterior de su respuesta. Prueba mínima con Gemini real, sin consultar datos ni herramientas: una elección explícita de 3.7 devolvió cuota 429, y el reintento automático produjo una respuesta guardada. El selector conserva el modelo realmente utilizado. La cuota externa sigue siendo variable.

Capturas: [oficina-ia.png](evidencias/oficina-ia.png), [oficina-ia-movil.png](evidencias/oficina-ia-movil.png), [oficina-ia-chat.png](evidencias/oficina-ia-chat.png).

Resultados completos del cierre: registrados en `seguimiento.md` → P17. La validación SQLite no demuestra concurrencia MySQL; la migración y las consultas nuevas sí se comprobaron en el MySQL real de pruebas. Publicación y usuarios humanos siguen pendientes de otra etapa.

**Corte anterior P17-06 a P17-09:** 359 pruebas backend SQLite (345 correctas, 14 omitidas de MySQL), las 14 carreras correctas en MySQL aislado, 166/166 frontend, lint cero errores/veinte avisos previos y build correcto. Evidencias nuevas: [plano ampliado](evidencias/oficina-ia-automatizaciones.png), [ficha](evidencias/oficina-ia-ficha.png), [programación](evidencias/oficina-ia-programar.png), [móvil](evidencias/oficina-ia-ampliada-movil.png). Gemini simulado únicamente en las regresiones aisladas; no se creó una automatización ficticia en pruebasv3 ni se hizo una nueva llamada real al proveedor.


## Corte actual P17-10 a P17-13

169/169 pruebas frontend en 33 archivos; lint cero errores y veinte advertencias existentes, build correcto. 361 pruebas backend SQLite, 347 correctas y 14 omitidas que requieren MySQL. Esas catorce se validaron en MySQL aislado en P17-09; no se modificó la concurrencia en esta revisión. Nuevas regresiones: doble superficie y mobiliario, apertura sin navegar, cambio de agente/borradores/cierre/ampliación, historial general, carga antes de enviar, ambiente Entrenamiento y conservación de IDs/perfiles/conversaciones/personalizaciones al migrar. Sintaxis Python y generación de migraciones correctas.

Se comprobó en navegador con datos de pruebasv3: las proporciones y puestos, el aula y descanso, chat integrado e historial real, cambio de agente, borrador conservado, chat ampliado y entrada visible en 390 × 844 sin recorte lateral. No se enviaron preguntas nuevas ni se sembraron automatizaciones o usuarios. El futuro formador lo configura el usuario desde Gestionar agentes, ubicándolo en Entrenamiento; una automatización semanal puede generar una clase y preguntas en el chat. Un sistema de exámenes interactivos, entrega a vendedores y calificaciones aún requiere implementación específica. No está implícito en el aula ni en una tarea de generación.
