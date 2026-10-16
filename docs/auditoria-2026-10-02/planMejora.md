# Plan de mejora e implementación del ERP Lottus Kemi

Fecha de elaboración: 2 de octubre de 2026.  
Estado: **en ejecución desde 2026-10-02**, nada desplegado todavía (rama `auditoria-2026-10-02`, sin commit). Leyenda de casillas: **[x]** validada localmente con pruebas; **[~]** parcial (la nota entre paréntesis dice qué está hecho y qué falta); **[ ]** sin empezar o bloqueada. El detalle y la evidencia de cada tarea están en [seguimiento.md](seguimiento.md); lo que exige el despliegue, en [operacion.md](operacion.md) → "Lista de despliegue". Última actualización de casillas: 2026-10-09.  
> **⛔ Módulos eliminados por decisión del usuario (2026-10-06, D-ALCANCE) — NO volver a crearlos:** Cuentas por pagar (abonos parciales y programación de pagos), Cartera, Conciliación, Turnos de caja, Posventa y Garantías, Excepciones y Conteos de inventario. Se borraron del frontend, el backend, la base y las pruebas. Las tareas del plan que los pedían quedan «fuera del alcance actual» aunque su texto original diga otra cosa. Solo el usuario puede revertirlo, de forma explícita.

Repositorios: **ordenesPedidoSW** (React) y **ordenesPedidoSWBackend** (Django).  
Fuente principal: [informe.md](informe.md), acompañado por [resultados.json](resultados.json) y [reproducciones.py](reproducciones.py).

### Entrega activa — coordinación de áreas e interacciones (2026-10-09, P18)

Solicitud: IA Lottus coordina los líderes reales; recorrido diario, actualización de Coach y ventas cada hora desde 09:50 Bogotá, informe compartido para Oscar y Stiven y activación por «dame un informe de las áreas» en el chat general. Solicitudes a gerencia y entregas generan visitas animadas entre personas.

- [x] **P18-01. Persistencia y programación.** Configuración compartida, destinatarios explícitos, líderes por zona, cola duradera, exclusión de solapamiento, clave idempotente, recuperación sin repetir llamadas y horario de Bogotá. Migración 0067 aplicada sola en pruebasv3 con respaldo parcial verificado; 0057/0061 no ejecutadas. Coach y analista existentes; cuentas reales de Oscar y Stiven. Horario inicial 09:50–18:50, todos los días, editable en /IA; cierre provisional a falta de una preferencia del usuario.
- [x] **P18-02. Evidencia y análisis.** Avance de cada persona activa invitada basado en trabajos registrados, fechas de entrega y gestión comercial; plan por cada venta pendiente y seguimiento de pedidos atrasados para el analista. Desglose compartido sin duplicar el total de ventas; no inventar vencimiento financiero, clases, exámenes ni métricas de aprendizaje. Fallos de Gemini conservan la evidencia como informe parcial. Última evidencia compartida disponible al coordinador; comparar cambios desde la captura anterior.
- [x] **P18-03. Chat e interacciones.** La frase en la IA general encola el informe solo para sus destinatarios autorizados; historial privado enlaza al informe compartido. Eventos persistentes del recorrido y de solicitudes/entregas; texto genérico visible en el plano, sin contenido privado. Un usuario puede dirigir la solicitud a Oscar o Stiven; solo quien atiende/responsable puede entregar. Sin reejecutar trabajo por una animación ni duplicar la visita al repetir el estado.
- [x] **P18-04. Interfaz y validación integral local.** Informe con gráficos, avance por persona, búsqueda/paginación del plan comercial, resultados por área y programa editable. Recorridos por pasillos, globos y movimiento reducido; detener paseos ambientales durante interacciones. 410 pruebas backend SQLite (389 correctas, 21 de MySQL omitidas), siete de concurrencia correctas en MySQL 8.4 desechable y 202 frontend en 37 archivos; lint 0 errores/20 avisos previos, sintaxis, migraciones y build. API localhost:8000 y frase en chat comprobadas; informes reales con 8 personas/801 ventas, sin envío a Gemini. Vista temporal de solo lectura del componente real: escritorio de 800 px, móvil 390 × 844, búsqueda, expansión y recorridos con eventos reales; eliminada después de verificar. Motor local activo con pruebasv3. Proveedor real pendiente en P18-06.
- [x] **P18-05. Continuidad y entrega.** Contrato, activación, alcance, respaldo, evidencia y requisitos en [coordinacion-areas.md](coordinacion-areas.md) y seguimiento. No publicado ni modificado producción. Falta definir cierre/días, asignar líderes de las otras áreas y registrar clases/exámenes; el informe señala estas ausencias.
- [ ] **P18-06. Autorización y prueba del análisis externo.** La revisión automática rechazó la prueba que enviaría datos internos a Gemini sin autorización explícita. Solicitud concreta presentada al usuario; **no habilitar ni enviar mientras no autorice**. Alternativa implementada y activa: `modelo=''` usa solo ERP y no adjunta el informe a otros chats de Gemini. Tras autorización humana explícita, activar desde Programa con modelo y `autorizar_envio=true`, generar un informe, comprobar respuestas/errores reales y actualizar plan/seguimiento. No confundir pruebas con proveedor simulado con validación real. Si decide mantener solo ERP, registrar esa decisión de alcance y cerrar este punto sin llamadas externas.

**Modo actual P18:** solo ERP. La memoria para Gemini y el análisis externo requieren autorización explícita; la interfaz y API rechazan activarlos por primera vez sin confirmar el envío. Las entregas se fechan al completar, no al comentar después; el latido de presencia no se interpreta como avance de trabajo.

### Entrega anterior — oficina virtual de agentes LOTTUS (2026-10-08, P17)

**Ampliación solicitada:** mantener el estilo aprobado; ampliar el plano horizontalmente con Gerencia, Oficina, Área comercial, Tecnología, Desarrollo creativo y Zona social. Ficha al acercar el mouse o enfocar un agente con información personal real, trabajo activo, próximas tareas y resultados. Automatizaciones por agente persistentes, ejecutadas por un proceso del servidor y consultables desde la plataforma; no son automatizaciones del escritorio Codex.

- [x] **P17-06. Oficina ampliada e interacción.** Gerencia, Oficina, Área comercial, Tecnología, Desarrollo creativo y Zona social en un plano horizontal de seis zonas, con mobiliario propio, arrastre/flechas y zoom. Fichas por acercamiento/foco, próximas tareas, actividad y resultados personales; acceso equivalente en móvil. Zonas y perfiles existentes conservados; sin empleados ficticios. Comprobada en escritorio y móvil de 390 × 844.
- [x] **P17-07. Programación por agente.** Crear/editar/pausar/archivar/restaurar tareas personales, una vez/diarias/semanales/mensuales, hora de Bogotá, modelo opcional, fecha límite y ejecución manual con idempotencia. Plantillas de instrucciones editables, no tareas sembradas. Reutiliza permisos existentes de uso/gestión de IA y propiedad privada por responsable. Historial persistente, restauración pausada y errores de calendario/estado explicados.
- [x] **P17-08. Motor y resultados.** Comando independiente `ejecutar_automatizaciones_ia`, activo en local con pruebasv3. Cola persistente, reserva sin duplicados, exclusión de solapamiento, revisión de usuario/perfil/permisos, cuota compartida de 40 consultas/hora y recuperación de interrupciones sin reintento automático. Resultados privados en chats y copia conservada si se elimina la conversación. Ficha y panel con trabajo real, próximo horario, resultados sin leer y latido del motor.
- [x] **P17-09. Verificación y operación local.** 359 pruebas backend SQLite: 345 correctas y 14 omitidas de MySQL; las 14 de concurrencia pasaron en MySQL 8.4 desechable, incluidas cinco nuevas de IA. 166 pruebas frontend en 33 archivos; lint 0 errores/20 avisos previos, build, sintaxis y migraciones correctos. Navegador: seis áreas, zoom/desplazamiento, fichas, formularios y móvil. **0063 aplicada sola en pruebasv3** tras respaldo parcial verificado `pruebasv3_ia_antes_programacion_20261008_233631.sql.gz`, perfiles y conversaciones conservados, 0057/0061 sin aplicar. Guía [automatizaciones-ia.md](automatizaciones-ia.md), capturas y plantilla de servicio preparadas. No publicada ni tarea nueva ejecutada con Gemini real; el usuario define su primer horario desde la interfaz. Inicio automático en producción queda para el despliegue autorizado.


**Ampliación del 9 de octubre:** Comercial con superficie doble y siete escritorios; Gerencia con tres; Zona social con cafetera, sofá de tres plazas y tres sillones; Tecnología cambia a Entrenamiento. Chat integrado a la oficina y diseño coherente, transiciones suaves y ampliación opcional.

- [x] **P17-10. Distribución compacta y mobiliario.** Contorno y ancho anteriores conservados: Comercial ocupa exactamente dos unidades de superficie y las otras cinco áreas una unidad cada una. Siete escritorios comerciales (uno para el analista existente y seis vacíos), tres en Gerencia (dos vacíos), cafetera, sofá de tres plazas y tres sillones de descanso. Planta compacta en dos filas más una franja comercial, sin crear empleados ni perfiles.
- [x] **P17-11. Entrenamiento.** Tecnología renombrada conservando ID y perfiles mediante **0064 aplicada sola en pruebasv3**, después del respaldo parcial verificado `pruebasv3_ia_antes_entrenamiento_20261009_001803.sql.gz`. Aula con pantalla LOTTUS Academia, escritorio del futuro formador y seis sillas. El usuario crea luego el agente y la tarea semanal; clases y evaluación interactiva quedan para otra solicitud.
- [x] **P17-12. Conversación integrada.** Panel lateral no modal sobre la oficina, entrada/salida suave con movimiento reducido, historial por agente y general, cambio de agente, borradores separados conservados durante la visita y ampliación voluntaria con la conversación/borrador actuales. Identidad negra y tonos cálidos también en los chats directos. Carga del historial aislada y bloqueo temporal de envío para no abrir otra conversación por accidente.
- [x] **P17-13. Verificación y continuidad.** 169 pruebas frontend en 33 archivos, lint 0 errores/20 avisos previos y build correcto; 361 backend SQLite: 347 correctas y 14 de MySQL omitidas, ya validadas en la entrega anterior sin cambios de concurrencia. Sintaxis y migraciones correctas. Navegador con datos reales: proporción/mobiliario, historial, borradores, panel, ampliación y móvil de 390 × 844. Capturas y guías actualizadas; 0057/0061 siguen sin aplicar. No publicado; sin agentes ni tareas ficticias.

**Ampliación activa: personas y colaboración (2026-10-09).** Selección explícita de usuarios activos dentro de /IA, identidad humana separada de perfiles IA, tareas/solicitudes/comunicación/avisos y señales personales de ventas; sin ampliar acceso comercial ni volver a crear módulos retirados.

- [x] **P17-14. Equipo humano seleccionado.** Responsable de oficina configurado por administración, elección discreta de personas existentes, zona/puesto, estado y presencia real. Acceso de invitados sin dar permisos de IA; conservación al retirar participantes.
- [x] **P17-15. Colaboración de personas.** Mensajes privados y del equipo, un destacado por persona con caducidad y burbuja entre comillas, tareas personales/asignadas, solicitudes al responsable y comentarios/estados; bandeja personal y datos de ventas según permisos.
- [x] **P17-16. Altura y circulación.** Quitar Header general solo en /IA, preservar menú móvil y acceso al perfil. Pasillos reales más amplios, sin movimiento de personajes, manteniendo siete escritorios comerciales, tres en Gerencia y superficie comercial doble.
- [x] **P17-17. Verificación y operación.** Regresiones de propiedad, participantes/privacidad/permisos y concurrencia; interfaz y navegador, migración explícita tras respaldo, actualización del plan/guías/evidencias. No publicar ni ejecutar 0057.

Solicitud: oficina original de LOTTUS en `/IA`, con zonas, personas que representan los perfiles reales de IA, chat e historial por agente y acceso al historial general. Las referencias visuales orientan la idea, sin copiar su diseño. Incorporar usuarios humanos queda para una etapa posterior.

- [x] **P17-01. Oficina y navegación.** Escena isométrica SVG original con muebles, escritorios, plantas, ambientes de showroom/estudio/operaciones/finanzas y personajes interactivos. Vista Equipo, búsqueda, filtros de zona y acceso general. `/chat` redirige a `/IA`; menú y cabecera actualizados. Comprobada en navegador de escritorio y móvil; los puestos adicionales se recorren por grupos.
- [x] **P17-02. Zonas y ubicación persistentes.** Modelo `ZonaOficinaIA`, FK opcional en `PerfilAsistente`, API de lectura/creación/edición y selector de zona. Administración requiere `USAR_ASISTENTE_IA` y `GESTIONAR_PERFILES_IA`; usuarios lectores consultan. Migración **0062 aplicada sola en pruebasv3**, con destino explícito que no ejecutó 0057. Respaldo parcial de perfiles y registro de migraciones verificado: `respaldos_locales/pruebasv3_perfiles_antes_oficina_20261008_223235.sql.gz`. Crea cuatro zonas de configuración y ubica los perfiles existentes; no genera agentes ni registros comerciales ficticios.
- [x] **P17-03. Chats e historial.** `/IA/agentes/:id` filtra conversaciones personales en servidor; `/IA/general` reúne las de todos los agentes del usuario. Continúa la última conversación desde el puesto, conserva modelos, gráficos y aprendizaje. Actividad basada en mensajes reales en proceso (ventana de cinco minutos), sondeo de actividad y paginación del historial. Verificado en navegador con respuesta real, actividad al salir del chat y recuperación del historial; el resumen conserva disponibilidad para continuar conversando.
- [x] **P17-04. Verificación, evidencia y continuidad.** Cuatro regresiones API y doce regresiones UI nuevas. Corte final: 334 backend en SQLite (325 correctas, 9 omitidas de MySQL), 156 frontend en 32 archivos; lint 0 errores/20 advertencias previas, build, sintaxis y migraciones sin cambios pendientes de generar. Vista móvil y capturas guardadas; guía [oficina-ia.md](oficina-ia.md). No se ha publicado.
- [x] **P17-05. Identidad visual LOTTUS.** Rediseño solicitado después de revisar la primera oficina. Referencia: [muebleslottus.com](https://muebleslottus.com), inspeccionada en navegador. Marca en Audiowide regular 400, blanca sobre negro, también en el letrero de la escena y en el menú. Cabecera y controles sobrios; planta arquitectónica propia con panel de listones de madera, vidrio, estructura negra, tapizados neutros, muestrario, escritorios con patas metálicas, sofá, archivo y zona de compras. Personas con proporciones y vestuario más discretos; tarjetas compactas y selector de zona sin etiqueta visual duplicada. Conserva perfiles, zonas, conversaciones y permisos existentes. Verificado con datos reales de pruebas en escritorio y móvil de 390 × 844: filtros, zonas adicionales, chat de agente e historial general; móvil abre Equipo sin desbordar la página. 156/156 pruebas frontend, lint 0 errores/20 avisos previos y build correcto. Evidencias: [escritorio](evidencias/oficina-ia-lottus.png) y [móvil](evidencias/oficina-ia-lottus-movil.png). Sin migraciones ni escrituras de negocio; no publicado.

### Entrega actual — web, navegación e IA (2026-10-08, P16)

Alcance explícito del nuevo prompt: también `webLottus`. Se continúa el trabajo previo sin sustituir datos de pruebas por fixtures. **ERP en localhost:3000 y API en localhost:8000, conectada a `pruebasv3`; catálogo local en localhost:4000. No se ha publicado esta entrega.**

- [x] **P16-01. Fichas web con cuatro secciones.** Descripción corta, descripción larga, características y materiales con campos extensibles, barra de negrilla/cursiva, viñetas, numeración, subtítulos, separadores y vista previa. Formato almacenado como texto; HTML escapado. `paginaweb 0005` conserva características/dimensiones antiguas en la nueva sección y ya está aplicada en la base real de pruebas. Precios retirados de formulario, tabla, tarjetas, detalle, variantes, ordenación pública y API; valores históricos conservados en base. Verificado con Sala Finlandia existente. Los productos sin textos siguen vacíos, sin contenido inventado.
- [~] **P16-02. Retirar Bancos por completo.** Página, menú, ruta, permisos del formulario, servicios, lectores de extractos, modelos y pruebas específicas retirados; se conserva la paginación compartida con Clientes y los medios de pago de recibos/egresos. Migración `ordenes 0057_eliminar_bancos` preparada y validada en SQLite desechable. **Pendiente aplicar en pruebasv3:** la revisión automática rechazó la eliminación de tablas por considerar insuficiente la autorización adjunta. Tablas/permisos persistidos aún intactos. Pedir confirmación explícita antes de ejecutar esa migración. No recrear el módulo.
- [x] **P16-03. Navegación única y estructura solicitada.** General: Inicio, Ventas, Pedidos, Telas, Remisiones, Facturas proveedor, Inventario. Finanzas: Caja, Recibos de caja, Comprobantes de egreso, Nómina. Bases de datos; Productos: Gestión web, Consultar precios, Administrar lista; IA: IA Lottus. Consulta de precios usa coincidencia exacta: no aparece activa a la vez que Administración. Pruebas en tres rutas y comprobación visual.
- [x] **P16-04. Editor de referencias.** Paneles para multiplicador/notas/cargos/precios por grupo, diseño adaptable, distinción calculado/manual y botón de expansión accesible. Conserva mutaciones, cálculos y guardado al salir del campo. Revisado con Alaska / Sofá 3p. de la base real.
- [x] **P16-05. Analítica y gráficos de IA.** `consulta_datos` usa ORM parametrizado y listas de campos permitidos: ventas, productos confirmados, pedidos, cobros confirmados e inventario; fechas incluidas, filtros, totales completos y hasta 50 grupos con aviso de truncamiento. Rechaza SQL libre, campos y filtros ajenos, fechas inválidas y rangos excesivos. `graficar_consulta` solo usa valores consultados en el mismo turno; admite barras, líneas y dona con controles de integridad. También grafica asesores (Total/N) y períodos comerciales. Guarda hasta tres gráficos por respuesta en la conversación; UI con tabla accesible, fuente/filtros/notas y PNG. Consultas repetidas se reutilizan, máximo 16 llamadas y ocho rondas, contexto de texto limitado y resultados acotados. Contexto estratégico actualizado (crecimiento, caja, fabricación bajo pedido, escenarios/hipótesis, estacionalidad, antigüedad sin mora). Se corrigieron sumas de precios de lista por cantidad y recaudo confirmado en herramientas existentes.
- [x] **P16-06. Validación y documentación.** Backend: corte completo de 309 pruebas (300 correctas, 9 omitidas de concurrencia MySQL), seguido de 24 pruebas dirigidas correctas con una regresión adicional de límite de tamaño; frontend: 135 pruebas en 28 suites; lint: 0 errores y 20 advertencias existentes; 11 pruebas dirigidas frontend y build repetidos tras los ajustes finales, sintaxis correcta. Pruebas aisladas cubren persistencia de formato, ausencia de precios, backfill, escape HTML, navegación, filtros, totales del top, cantidades, pagos anulados, gráficos con fuente válida, caché y persistencia. Consultas de solo lectura ejecutadas en los cinco dominios y agrupaciones temporales contra MySQL real de pruebas; total de ventas contrastado independientemente. Resultado por sede: 1.058 caracteres para el modelo. Prueba del proveedor Gemini simulada, sin enviar cifras reales a un servicio externo ni medir consumo facturado. No se afirma reducción porcentual de tokens ni despliegue.

### Corrección solicitada — tamaños y chat (2026-10-08, P16-07/08)

- [x] **P16-07. Editor compacto.** Reemplazados los estilos amplios de la entrega anterior por reglas encapsuladas en `lp-admin-page`: campos de 28 px, cabeceras de variante de 54 px verificadas en navegador, espaciado de 6–10 px, filas de precios continuas y textos de ayuda breves. Se compactaron tanto la referencia como cada variante y sus secciones de margen, notas, cargos y grupos. Conserva los cálculos, valores y guardado existentes; no se modificaron precios reales. Evidencia: [precios-compactos.png](evidencias/precios-compactos.png).
- [x] **P16-08. Chat operativo y selector de modelo.** Causa comprobada en `runserver.log`: MySQL cerraba el socket durante la espera a Gemini; fallaba el guardado de la respuesta y también del error, dejando el mensaje en `procesando`. Ahora libera conexiones antes de llamadas externas, reconecta al guardar y reintenta una vez el UPDATE idempotente. El trabajo se inicia después del commit; el vencimiento no sobrescribe respuestas ya terminadas. Selector con modo automático y elección explícita validada por el servidor; el modelo real aparece en cada respuesta. Errores 429, indisponibilidad, timeout y configuración separados; no se muestran mensajes crudos del proveedor ni claves en URL. Sondeo frontend limitado ante fallos de red, con reanudación sin duplicar preguntas. Presupuesto de razonamiento ajustado por familia y tiempo de análisis acotado.
- [x] **Validación del arreglo:** 319 pruebas backend (310 correctas, 9 omitidas de MySQL), 137 frontend/28 suites; lint sin errores (20 advertencias existentes), build, sintaxis y comprobación de migraciones correctos. Nueve regresiones backend y dos frontend nuevas. **Esta vez se verificó Gemini real:** catálogo de modelos, respuesta simple con 3.6, error de timeout guardado correctamente y reintento desde UI con 3.5 Flash Lite que produjo consulta y gráfico sobre pedidos existentes (septiembre 2026), con tabla/fuente y persistencia. 3.8 y 3.5 Flash devolvieron HTTP 429 en las comprobaciones; 3.7, 3.6 y variantes Lite respondieron a la prueba mínima. Esto no garantiza disponibilidad futura ni elimina cuotas externas. Evidencia: [chat-modelo-grafico.png](evidencias/chat-modelo-grafico.png).

No hay nuevas migraciones ni publicación en este arreglo. Se mantienen localhost:3000/8000 y la base real de pruebas. P16-02 continúa bloqueada, sin ejecutar el borrado de Bancos. Ver [chat-y-editor-compacto.md](chat-y-editor-compacto.md) para diagnóstico, cambios, pruebas y límites.

**Respaldo de esta entrega:** `respaldos_locales/pruebasv3_antes_web_bancos_20261008_165357.sql.gz`, completo y descompresión verificada, permisos 0600. La primera conexión expiró después del respaldo; la migración web se ejecutó con una conexión nueva. El respaldo no equivale a un ensayo de restauración de esta entrega.

**Siguiente paso concreto:** confirmación para aplicar únicamente `ordenes 0057` en la base de pruebas; después verificar ausencia de tablas/permisos de Bancos y mantener comprobantes/recibos intactos. Publicación de los tres repositorios sigue pendiente y es distinta de esta validación local. Detalles y limitaciones en [web-navegacion-ia.md](web-navegacion-ia.md).

### Continuación activa — productos vendidos y nómina

**Nuevo alcance solicitado por el usuario:** cada venta tendrá el desglose completo de productos, variantes, grupo de tela y adicionales; se usará el precio de lista registrado al vender para la nómina. El auxiliar puede registrar la cabecera y el vendedor completar los productos. Se prioriza venta bajo pedido (aproximadamente 96 %, según el usuario), con continuidad venta → pedido a proveedor → factura/recepción → remisión. Las descripciones para proveedor y cliente serán independientes y modificables. El vínculo con inventario será una ayuda opcional, no un requisito para vender.

**Trabajo en curso:** P15, definido más abajo. No se declara implementado hasta validar API, UI, documentos y nómina. Se respetan D-ALCANCE y la sustitución de Comisiones por Nómina (D12a). Las cifras del avance anterior son históricas: durante la continuación se retiraron módulos y se añadió Nómina. El corte actual ejecuta 300 pruebas backend en SQLite (todas correctas y 10 de MySQL omitidas), 113 pruebas frontend en 25 suites, y 2 pruebas nuevas de concurrencia en MySQL desechable.

**Avance previo que se conserva:** exportaciones operativas en servidor de ventas, recibos, egresos e inventario, con filtros, texto literal, auditoría y permisos; listado de recibos limitado a ventas visibles. Los cambios de posventa/turnos no se reintroducen tras D-ALCANCE. P14 tiene un recorrido financiero por API y un escenario local desechable; faltan navegador/operadores e infraestructura real. Se consolidará al finalizar una guía única de decisiones/acciones del usuario y pendientes técnicos.

### Último avance registrado — 2026-10-06

**Última entrega validada localmente:** P13-04 se adelantó a la fusión para corregir rutas que revelaban ventas/comisiones ajenas y registrar la generación de exportaciones en el servidor. Clientes exporta XLSX autorizado; el historial comercial, las comisiones y su CSV respetan el alcance del usuario. La fusión de P13-03 continúa pendiente. **D06d es provisional, no una respuesta del usuario:** se conserva la consulta global de fichas básicas y la política existente de edición mientras se define el acceso entre vendedores.

| Tarea | Estado real | Implementado / decisión | Falta |
|---|---|---|---|
| P13-01 | Parcial | SIIGO confirmado e inventario técnico de documentos registrado | Verificar responsables y flujo fiscal externo antes de una eventual integración |
| P13-02 | Fuera del alcance actual por decisión del usuario | No se necesitan exportaciones ni conexión con SIIGO por ahora | Reabrir únicamente si el usuario solicita intercambio; no hay adaptador implementado |
| P13-03 | Parcial, con entrega validada localmente | Módulo `/calidad-clientes`: correcciones seleccionadas con originales, autor y fecha; candidatos explicados; comparación; permisos, idempotencia y protección ante ediciones simultáneas; migración 0047 preparada | Fusión ejecutable que preserve identidad histórica y todas las relaciones de documentos |
| P13-04 | Parcial, con entrega validada localmente | XLSX de clientes en servidor con permisos, alcance, filtros, límite y auditoría; historial comercial y notas por alcance; CSV, totales y tasas personales de comisiones; texto seguro en archivos | Otras exportaciones e impresión, adjuntos y rutas directas; confirmar política de directorio/edición (D06d) y conservación/solicitudes (D06b) |
| P14 | En curso | P14-01 validada en local; P14-02 a P14-05 preparadas (aceptacion-y-publicacion.md) | Ejecutar guiones con operadores, pruebas en el VPS y publicación autorizada |

**Última validación registrada:** MySQL **369/369**; SQLite **355 ejecutadas correctamente y 14 omitidas** por requerir MySQL; frontend **143/143 en 28 suites**; lint sin errores y con 22 avisos; build, `py_compile` y comprobación de migraciones correctos. P13-04 añade 29 regresiones de backend y 9 de interfaz. Evidencia, comandos y límites en [validacion.md](validacion.md). Sin nuevas migraciones ni despliegue en esta entrega.

**Siguiente trabajo:** continuar P13-04 por las exportaciones de ventas, recibos, egresos e inventario y la descarga/acceso directo a evidencias de posventa; completar la fusión de P13-03 preservando los documentos históricos. Confirmar D06d para el directorio/edición y resolver D06b antes de implementar eliminación o anonimización. Inventario y pasos en [exportaciones-y-datos.md](exportaciones-y-datos.md). La migración 0047 solo está probada en bases desechables; no se declara aplicada a la base operativa.

### Incidente de entorno local resuelto — 2026-10-07

El servidor que ocupaba `localhost:8000` estaba arrancado con el `.env` de operación y consultaba un MySQL externo sin la migración `ordenes 0051`; por eso `GET /api/dashboard-stats/` y `GET /api/ventas/` devolvían `500` por la columna ausente `ordenes_venta.revision_productos`. La base de datos de pruebas real recibió únicamente esa migración requerida. No se modificó producción.

La fixture ficticia de aceptación se usó solo para diagnosticar el arranque y ya fue retirada del flujo. Se restauró `db_local.sqlite3` desde `respaldos_locales/db_local.sqlite3.before-aceptacion`; no contiene los usuarios ni las ventas de demostración y no es la fuente activa del servidor. El `runserver` local está marcado explícitamente con `.local-test-db` para cargar las credenciales ya existentes en `.env` y conectarse a la base MySQL de pruebas `u756180748_pruebasv3`. El código no copia esas credenciales a archivos, commits, logs ni documentación. El frontend continúa en `http://localhost:3000` apuntando a `http://localhost:8000/api`.

La migración 0051 se aplicó en esa base de pruebas real mediante un puente local temporal, que ya fue retirado. El log actual muestra `200` para `/api/user/`, `/api/vendedores/`, `/api/listar-pedidos/`, `/api/ventas/` y `/api/nomina/cierres/`; la vista de Ventas mostró identificadores y nombres existentes en la base de pruebas, no filas inventadas. También se corrigió en `Ventas.jsx` el ciclo de `setSearchParams` que provocaba `Maximum update depth exceeded` cuando la consulta de vendedores fallaba o aún no tenía datos. Se ejecutaron `py_compile`, `manage.py check`, ESLint (0 errores), las pruebas frontend y el build. Esto es una corrección del entorno local contra la base de pruebas; no equivale a despliegue ni a reparación de datos operativos.

## 1. Objetivo y alcance para el agente ejecutor

Implementar de forma gradual todas las mejoras del informe: **34 hallazgos técnicos, 10 mejoras de experiencia y 16 propuestas funcionales**. Cada cambio debe conservar los datos, respetar las reglas comerciales, demostrar su resultado con pruebas adecuadas y dejar instrucciones de operación y recuperación.

Mantener React y Django como un monolito modular. La auditoría no justifica una reescritura, microservicios ni un rediseño visual general. Trabajar por entregas pequeñas que resuelvan un comportamiento completo entre API, interfaz, datos y operación.

Las propuestas funcionales requieren decisiones de negocio antes de activar sus reglas. Están incluidas en el plan, pero no se deben inventar políticas de comisiones, impuestos, crédito, aprobación o conservación de datos. Una decisión pendiente se registra y se continúa con trabajo independiente; no se declara implementada una funcionalidad por haberla diseñado.

Las fases son un orden de dependencias, **no un calendario prometido**. Solo estimar esfuerzo después de revisar el estado actual, los datos disponibles y las decisiones necesarias.

### Fuentes que se deben leer al comenzar

1. Este plan, el informe y sus evidencias.
2. Las instrucciones AGENTS.md aplicables, incluida [.agents/AGENTS.md](/Users/stiven/Desktop/Coding/pruebaLottusKemi/.agents/AGENTS.md), y cualquier instrucción nueva dentro de los repositorios.
3. Los documentos de la raíz generalidades.md, INSTRUCCIONES_PROYECTO.md, lista_precios.md, ENVIRONMENT_CONFIG.md y DEPLOY_VPS.md, junto con las guías internas de los dos repositorios.
4. El código, las migraciones, los contratos API y las pruebas vigentes. Los documentos antiguos pueden discrepar de la implementación; registrar cada contradicción y resolverla con las reglas vigentes y el responsable del proceso.

**No copiar valores de credenciales de esos documentos** a archivos, mensajes, pruebas, registros o commits. Las referencias y números de línea del informe son puntos de entrada de la fotografía auditada; localizar nuevamente los símbolos antes de modificar.

La fotografía auditada corresponde al backend HEAD 0a482562 y frontend HEAD 3a2417e, **incluidos cambios locales y archivos sin versionar del frontend**. Revisar diferencias actuales: no asumir que HEAD contiene todo lo auditado ni que coincide con producción.

## 2. Límites de autonomía y reglas que no pueden cambiar silenciosamente

- Implementar en los repositorios autorizados. P16 incorpora explícitamente `webLottus`; `landingLottus` sigue fuera del alcance. Leer los documentos de contexto de la raíz.
- Conservar todo cambio previo del usuario. No usar limpieza, restauración o reinicio destructivo de Git. Un checkout aislado no incluye automáticamente archivos locales: asegurar primero que la base elegida contiene el trabajo relevante.
- Esta entrega autoriza la creación del plan. Al recibir posteriormente la orden de ejecutarlo, avanzar con cambios locales reversibles, pruebas y documentación. No interpretar este archivo como autorización para intervenir producción, rotar accesos reales, reescribir historia compartida o reparar datos reales.
- Para una intervención externa de alto impacto todavía no autorizada, preparar primero cambio, evidencia, copia recuperable, alcance y reversión; solicitar únicamente la autorización que realmente falte. Respetar autorizaciones explícitas ya dadas en la sesión.
- Para pruebas automatizadas, usar fixtures solo en bases desechables. La plataforma local debe usar la base real de pruebas proporcionada por el usuario, sin sembrar datos ficticios. No ejecutar pruebas, migraciones exploratorias, envíos de correo o pruebas de carga contra producción. Los servicios externos deben tener dobles de prueba o entornos de ensayo.
- No afirmar que una vulnerabilidad fue explotada ni que existen datos corruptos en producción sin evidencia. El informe demuestra comportamientos posibles en el código local.
- No introducir una librería o un servicio operativo adicional sin justificar qué problema resuelve, cómo se mantiene y cómo se recupera.

### Invariantes de negocio

1. Las estadísticas **personales** de ventas compartidas atribuyen Total / N a cada participante único. Listados y detalle conservan el 100 % del importe. Una orden conserva a su creador real.
2. El saldo de caja nunca puede ser negativo. Recibos, egresos en efectivo y movimientos muestran avisos comprensibles; la protección real reside en el servidor y la base.
3. El PDF de egreso imprime siempre **“Pagado”**, como exige el negocio. La transferencia permanece pendiente en base de datos hasta confirmación autorizada; el efectivo queda pagado solo cuando su movimiento se aplica correctamente. Documentar esta diferencia sin alterar la regla unilateralmente.
4. Una orden requiere al menos un detalle válido, cantidades positivas y relaciones coherentes.
5. Los modales mantienen fondo opalizado completo y centrado; las cargas se muestran en el botón, tarjeta o región afectada.
6. Reutilizar tema, variables, clases y componentes existentes; encapsular CSS por vista. No introducir una estética disruptiva.
7. React Query administra consultas y mutaciones de servidor; AppContext contiene sesión y estado visual. Las peticiones salen de servicios de dominio y utilizan configuración Vite por entorno.
8. Mantener los precios por grupo globales y el multiplicador como entidad independiente. No volver al diseño antiguo de lista_precios.md.
9. Utilizar Decimal para importes y cálculos financieros, con precisión y redondeo explícitos. **No prohibir todo número negativo indiscriminadamente**: cargos comerciales intencionales como “Sin tapa” deben seguir funcionando.
10. Conservar el bloqueo actual de PUT y DELETE de remisiones mientras esas operaciones no tengan un diseño de negocio autorizado. Ambos controles funcionaban en la auditoría.

## 3. Método de trabajo, decisiones y evidencia

### Ciclo obligatorio por tarea

1. Localizar rutas, modelos, componentes y consumidores afectados; comprobar si el problema sigue vigente.
2. Definir contrato e invariantes. Para un fallo, escribir una regresión que falle por la causa observada y describir la salida esperada.
3. Implementar el cambio más pequeño que cierre el comportamiento completo. No mezclar una corrección crítica con una refactorización masiva.
4. Añadir o actualizar migraciones si hacen falta, con estrategia de compatibilidad y recuperación.
5. Ejecutar las comprobaciones relevantes, incluida compilación de sintaxis tras editar Python. Probar por API aunque la interfaz oculte una acción.
6. Revisar la diferencia completa, los permisos, las fugas de datos, los efectos secundarios y el impacto en clientes anteriores.
7. **Actualizar siempre este `planMejora.md` antes de entregar cada avance**, por instrucción expresa del usuario: cambiar el estado de las tareas afectadas, separar lo implementado de lo pendiente y registrar decisiones, pruebas, límites y siguiente tarea. Mantener sincronizados `seguimiento.md` y los documentos de evidencia que correspondan; no sustituir la actualización del plan por una nota solo en esos archivos o en el chat. Cerrar una tarea únicamente con evidencia verificable.
8. **Volver a leer el archivo guardado y verificar sus estados antes de responder.** Usar `[x]` para trabajo validado, `[~]` para parcial y `[ ]` para pendiente; dejar las tareas retiradas por decisión explícita como «fuera del alcance actual», sin casilla de implementación pendiente o completada. Si una tarea es parcial, desglosar los componentes completados y los restantes para que el siguiente agente pueda continuar sin repetir trabajo.

Mantener junto a este plan un **seguimiento.md** con una fila por tarea: ID, estado, repositorio/commit o cambios locales, prueba ejecutada, evidencia, decisión pendiente y siguiente paso. Estados: pendiente, en curso, bloqueada con causa, validada localmente, validada en staging, desplegada y verificada. No confundir estos estados.

Crear los siguientes documentos cuando empiece la ejecución, sin incluir secretos ni datos personales:

| Entregable | Contenido |
|---|---|
| decisiones.md | Pregunta, opciones, decisión, responsable, fecha y consecuencias |
| matriz-permisos.md | Rol, alcance de objetos, acción, campos visibles/editables y permiso |
| contratos-api.md u OpenAPI equivalente | Peticiones, respuestas, errores, paginación, idempotencia y compatibilidad |
| migracion-datos.md | Conteos, conciliaciones, lotes, excepciones y recuperación |
| validacion.md | Comandos, entorno, resultados, pruebas manuales y límites |
| operacion.md | Arranque, despliegue, backups, restauración, alertas y respuesta |

Al retomar trabajo, leer seguimiento y diferencias Git antes de actuar. Reanudar la siguiente tarea pendiente con sus dependencias satisfechas; no repetir ni descartar trabajo validado. Si el código cambió desde la auditoría, actualizar la evidencia y explicar el cambio de alcance.

### Decisiones que se deben resolver en su momento

| ID | Decisión | Momento límite y trabajo que puede continuar |
|---|---|---|
| D01 | Alcance de administrar usuarios, delegación de privilegios y separación preparador/aprobador | P02/P03: resolver antes de activar la política nueva; cerrar accesos por objeto y filtraciones independientemente |
| D02 | Aplicaciones de pago, descuentos, anticipos, sobrepagos, retenciones, anulaciones y períodos cerrados | P03 para las operaciones afectadas; P10 para ampliaciones. No inventar reglas tributarias ni saldos a favor implícitos |
| D03 | Precisión, redondeo, costo integral, vigencia de precios y reglas de comisiones | P05 para cálculos actuales; P09/P12 para funciones nuevas |
| D04 | Unidad física o cantidades, reservas, recepción sin factura, consignación, devoluciones y evidencia de entrega | P04 para invariantes existentes; P11 para ampliaciones |
| D05 | Volumen representativo, metas de rendimiento, navegadores/dispositivos y compatibilidad entre versiones | Medir desde P00; fijar objetivos antes de P08 |
| D06 | Alcance contable/fiscal, proveedor de integración y reglas de datos personales | P13; validar con responsables del negocio y especialistas cuando corresponda |
| D07 | Duración/revocación de sesión, MFA, recuperación y almacenamiento de tokens | P02, antes de cambiar autenticación |
| D08 | Pérdida máxima de datos tolerada, tiempo de recuperación, retención y responsables operativos | Antes de cualquier publicación o reparación real; ensayar en P07 |

## 4. Orden y dependencias

Ruta de trabajo habitual: **P00 → P01 → P02 → P03 → P04 → P05 → P06 → P07 → P08 → P09 → P10/P11 → P12 → P13 → P14**.

P03 y P04 comparten contratos de documentos, pagos e inventario. P05 puede desarrollarse una vez estabilizada la línea de pruebas. P07 empieza a prepararse desde P00: **no se posponen las pruebas, backups ni controles de entrega hasta terminar las correcciones**. Las mejoras visuales comunes de P08 pueden acompañar los flujos corregidos; el trabajo móvil con operaciones pendientes depende de P11 y de la idempotencia del servidor.

Una corrección urgente puede entregarse antes del fin de P07 si pasa las pruebas aplicables y un procedimiento de despliegue/recuperación verificado. No usar el script antiguo sin corregir sus fallos. No retrasar una rotación de credenciales expuestas hasta completar toda la hoja de ruta.

### Puertas de avance

- **G0 — Aislamiento:** configuración de pruebas sin acceso a producción, base desechable y pruebas base reproducibles.
- **G1 — Integridad:** P02–P05 verificadas; sin escrituras parciales, acceso indebido, doble aplicación ni pérdida de identidad.
- **G2 — Publicación segura:** datos/migraciones ensayados, respaldo restaurado, dependencias compatibles, CI y recuperación comprobadas.
- **G3 — Evolución:** contratos y operaciones estables; funcionalidades nuevas activadas por etapas con decisiones de negocio registradas.
- **G4 — Cierre:** toda la matriz de cobertura tiene evidencia; las limitaciones no se ocultan como tareas terminadas.

## 5. Fases de implementación

### P00 — Preparar una base verificable

**Cubre:** inicio de H23 y H34. **Dependencias:** ninguna.

- [x] **P00-01. Inventario del estado real.** Registrar versión de ambos repositorios, diferencias locales, archivos nuevos, runtimes, comandos existentes, esquema y entradas de despliegue. Leer las instrucciones aplicables. Crear seguimiento y decisiones. No adjuntar contenido de .env. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P00-02. Aislar pruebas.** Mantener SQLite en memoria para pruebas rápidas y definir un perfil MySQL desechable para integración/concurrencia, con usuario y base exclusivos sin acceso a producción. Desactivar correo real y otras salidas externas. Incorporar una comprobación que aborte si el destino no es de pruebas. *(parcial: SQLite y MySQL local listos; CI MySQL sin ejecutar en GitHub)*
- [x] **P00-03. Reparar descubrimiento.** Eliminar consultas a tablas durante la importación de test_dashboard.py; convertirlo en pruebas con datos creados por fixtures o preparación de casos. Mantener las 21 pruebas existentes de precios y los controles correctos del informe. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P00-04. Activar controles efectivos.** Configurar ESLint para JS/JSX además de los tipos realmente usados; agregar scripts de lint y pruebas de interacción, y una base de CI para ambos repositorios. No esconder fallos desactivando reglas globales o excluyendo el código afectado. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P00-05. Transformar evidencia en regresiones.** Conservar resultados.json como fotografía histórica. Clasificar sus 26 observaciones mediante el anexo A; crear regresiones por dominio con resultado esperado corregido. No tratar reproducciones.py como una suite que ya pasa. *(validada localmente 2026-10-02 — ver seguimiento.md)*

**Aceptación:** instalación documentada y reproducible; descubrimiento completo sin errores de importación; lint realmente procesa App.jsx; compilación frontend correcta; cada defecto tiene prueba asignada. Los casos que todavía fallan deben estar identificados, no presentados como corregidos.

**Entrega:** línea base, CI inicial, catálogo de pruebas y perfiles aislados. Ninguna intervención en datos reales.

### P01 — Contener exposición de secretos y separar entornos

**Cubre:** H01 y H16; requisitos operativos de H22/H34. **Dependencias:** P00.

- [x] **P01-01. Inventariar exposición sin mostrar secretos.** Buscar referencias a accesos en documentos, código, historial disponible, configuración y mecanismos de despliegue. Registrar únicamente servicio, entorno, ubicación, responsable y relación de reutilización. Preparar revocación/rotación coordinada de todos los accesos afectados, no solo cambiar un texto. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P01-02. Corregir selección de entorno.** Separar desarrollo, pruebas, staging y producción. DEBUG no debe seleccionar base, usuario ni credenciales. Respetar variables explícitas del proceso; documentar la precedencia de .env y eliminar sobrescrituras inesperadas. Rechazar configuración incompleta o ambigua sin revelar secretos. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [ ] **P01-03. Preparar y, con autorización vigente, ejecutar la rotación.** Usar credenciales distintas por servicio/entorno, llaves SSH, usuario de despliegue limitado y almacenamiento de secretos externo al repositorio. Secuenciar actualización de consumidores, verificación y revocación para evitar pérdida de acceso. *(bloqueada: requiere autorización y acceso para rotar (script nuevo preparado))*
- [~] **P01-04. Sanear documentación y prevención.** Reemplazar valores por ejemplos ficticios, revisar archivos versionados e ignorados y activar detección de secretos en cambios/CI. La reescritura de historia compartida requiere coordinación después de rotar. Como el alcance de edición es de los dos repositorios, preparar el cambio de documentos/scripts de raíz y pedir ampliación de alcance si hace falta aplicarlo allí; no declarar cerrada su exposición mientras permanezca. *(parcial: guía versionada saneada; historial y raíz pendientes)*
- [ ] **P01-05. Preparar recuperación.** Identificar backups existentes y acceso de restauración sin suponer que no existen. Obtener una copia recuperable autorizada antes de cambios reales; el ensayo completo se documenta en P07. *(pendiente: D08)*

**Aceptación:** matriz DEBUG verdadero/falso × entorno respeta DB_NAME/DB_USER/DB_HOST sin conectarse para comprobarlo; staging no puede acceder a producción con su cuenta. No quedan secretos activos en los lugares revisados una vez ejecutada la rotación. Registrar lo que no pudo verificarse, incluido remoto o VPS.

**Recuperación:** no reactivar secretos expuestos para revertir; disponer de credenciales nuevas de contingencia y procedimiento probado.

### P02 — Unificar autorización, sesión e impresión segura

**Cubre:** H05, H06, H07, H08, H17, H20, H21 y H28. **Dependencias:** P00/P01; D01 y D07 en lo pertinente.

- [x] **P02-01. Matriz de acceso por acción y objeto.** Enumerar CRUD, acciones personalizadas, rutas “completo”, exportación e impresión. Reutilizar consultas autorizadas para lectura/escritura de venta, orden, recibo, observación y remisión heredada. Separar edición de datos, cambio de estado, cliente y participantes. Evaluar también cada identificador relacionado recibido. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P02-02. Respuestas y mutaciones por permiso.** Quitar costos y datos restringidos de la serialización para perfiles sin permiso, incluidas relaciones anidadas, agregados y exportaciones. Exigir permiso de modificación en asignar-multiplicador y demás acciones personalizadas. Separar editar egreso de confirmar/revertir; ninguna escritura genérica admite saltarse el permiso. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P02-03. Catálogo único de permisos.** Definir códigos canónicos compartidos por backend, /user/ y frontend. Migrar alias y configuraciones de roles preservando acceso legítimo; distinguir rol sin configuración de una lista deliberadamente vacía. Sembrar mediante migración o acción explícita. GET de configuración no escribe ni cambia permisos. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P02-04. Administración de usuarios.** Resolver D01; separar altas/bajas, contraseñas y asignación de privilegios. Evitar autoelevación, proteger al último administrador utilizable y registrar actor/antes/después. Desactivar sin borrar historia y revocar sesiones cuando corresponda. No dejar al negocio sin un administrador durante la migración. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P02-05. Endurecer sesiones.** Resolver D07: tokens de acceso de duración menor, renovación con rotación y revocación, cierre de sesión del servidor y revocación por eventos relevantes. Definir si un acceso vigente se invalida inmediatamente o mediante vencimiento corto, y probar esa garantía. Diseñar MFA y recuperación para perfiles privilegiados. Si se eligen cookies HttpOnly/SameSite, implementar y probar CSRF/CORS/orígenes/HTTPS conjuntamente; no mover tokens a cookies sin esos controles. *(parcial: rotación/revocación hecha; duración y MFA esperan D07)*
- [x] **P02-06. Recuperar errores de sesión.** Compartir contadores de intentos entre procesos y comprobar IP real/proxy sin confiar en cabeceras arbitrarias. Añadir timeout, cancelación, renovación coordinada y salida visible de carga cuando /user/ falla con red, 401, 403 o 5xx. Evitar ciclos de renovación y reintento automático de escrituras no idempotentes. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P02-07. Eliminar inyección en impresión.** Sustituir document.write con datos concatenados por componentes de impresión o nodos DOM con texto seguro; revisar todas las salidas documentales. Probar nombres, códigos y descripciones con caracteres especiales y etiquetas como texto. Introducir una política de contenido compatible con impresión y librerías utilizadas, comprobando que no rompe funciones. *(parcial: QR seguro; CSP pendiente de prueba en navegador)*

**Aceptación:** matriz de pruebas positivas y negativas por rol/objeto/acción; venta ajena y sus variantes inaccesibles; datos sensibles ausentes del cuerpo, no solo ocultos; GET de permisos sin efectos; edición no confirma pagos; lector de precios no modifica; autoelevación rechazada según política acordada; sesión recuperable y cierre con revocación documentada; etiquetas QR sin ejecutar contenido.

**Entrega:** políticas reutilizables, migración de permisos, interfaz coherente con permisos efectivos y regresiones de API/navegador. Las verificaciones de sesión deben incluir dos pestañas, expiración y cambio de usuario.

### P03 — Hacer atómicos, conciliables e idempotentes los movimientos financieros

**Cubre:** H02, H03, H07, H09, H10, parte de H12/H15/H32; base de F05–F08. **Dependencias:** P02 y decisiones D02 necesarias para el alcance actual.

- [x] **P03-01. Servicios de operación completa.** Extraer crear/editar/confirmar/revertir cobro y egreso, así como movimientos de caja. Validar forma antes de escribir y volver a comprobar estado/saldo/relaciones dentro de la transacción con bloqueos. La operación incluye cabecera, líneas, aplicaciones, saldo, estado y bitácora. Capturar excepciones fuera de la unidad atómica; ningún 400/403/conflicto deja cambios parciales. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P03-02. Caja con entidad estable.** Introducir una cuenta de caja identificable por sede y la relación preparada para turnos. Bloquear esa fila para aplicar movimientos, incluso cuando aún no existe ningún movimiento. Crearla/configurarla de forma controlada con unicidad para evitar carreras de apertura. El saldo lo calcula el servidor; el cliente no lo fija. Rechazar cierre en el alta genérica; implementar acción de cierre con permiso propio. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P03-03. Importes y restricciones.** Exigir valores positivos para movimientos normales, impedir saldo negativo con protección transaccional y restricciones compatibles con MySQL. Modelar ajustes por dirección, motivo y autorización; no permitir que un “ajuste” o “cierre” eluda la regla de caja. Mostrar toast sin perder datos cuando falta efectivo. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P03-04. Confirmación única de pagos.** Una función decide los efectos según el medio vigente. Transferencia pendiente cambiada a efectivo y luego confirmada genera exactamente un ingreso de caja y un abono. Una reversión referencia al original y compensa una sola vez; no borra el movimiento previo. Proteger los cambios de medio de líneas ya confirmadas. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P03-05. Aplicaciones de egresos.** Verificar que existen todas las facturas enviadas, que pertenecen al proveedor y ámbito correctos, que están en estado elegible y tienen saldo disponible. Bloquear las filas en orden estable. Calcular el importe desde aplicaciones y conceptos estructurados, sin confiar en valor total enviado. No sustituir una regla de pagos parciales por igualdad de totales sin resolver D02. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P03-06. Concurrencia, repetición y numeración.** Bloquear pago/documento/caja y hacer transiciones condicionales. Incorporar claves de idempotencia en operaciones susceptibles de reenvío, con unicidad, alcance de usuario/operación, huella de petición y respuesta persistida dentro de la transacción. Misma clave y contenido no duplica efectos; contenido distinto produce conflicto. Usar contador por serie bloqueado o mecanismo equivalente; eliminar MAX(id)+1. Definir orden de bloqueos y tratamiento de conflictos/deadlocks. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P03-07. Historia y períodos.** Añadir relaciones documento↔pago↔aplicación↔movimiento↔reversión, autor, aprobación, fecha, motivo y versión. Prohibir borrar documentos contabilizados y sustituir correcciones por anulación/reversión autorizada. Definir cierre/reapertura de períodos y registrar toda excepción. Conservar la regla independiente del PDF. *(parcial: vínculos, autoría y bitácora; períodos pendientes)*

**Aceptación:** al fallar después de guardar una cabecera o una línea, todos los saldos, estados, vínculos y conteos quedan como antes. Caja vacía no admite egreso ni valor negativo ni cierre genérico. Confirmar dos veces, reintentar tras timeout y confirmar simultáneamente afectan una sola vez. Comprobante de proveedor A no modifica factura de B. Numeración concurrente sin duplicados. Ejecutar estas carreras con conexiones independientes en MySQL aislado, no solo SQLite.

**Entrega:** servicios financieros, restricciones, migraciones expansivas, contrato de errores y pruebas de conciliación. Activar la nueva ruta solo tras comparar saldos y conservar compatibilidad de clientes durante el cambio.

### P04 — Preservar inventario, validar compras y proteger reservas

**Cubre:** H04, H11, H12, H14, H15, H27 y parte de H33. **Dependencias:** P02; coordinar contratos con P03; D04 para reglas nuevas.

- [x] **P04-01. Editar por identidad.** Reemplazar el borrado/recreación de productos al editar factura por altas, modificaciones y bajas permitidas sobre identificadores estables. No cambiar PK/QR de unidades existentes por cambiar descripción o costo. Conservar telas, costos adicionales, grupos, traslados y vínculos con remisiones. Reservados, por despachar, despachados y entregados requieren reglas específicas; no eliminarlos silenciosamente. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P04-02. Validación anidada estricta.** Definir entradas tipadas para factura, productos y detalles de orden/tela. Comprobar referencia existente y del proveedor correcto, categoría/subcategoría, cantidades positivas, metrajes/rangos y ecuación del total con descuentos/cargos. Eliminar descarte silencioso y valores de respaldo ante errores. Una fila inválida rechaza el documento completo con error de campo/fila. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P04-03. Autorización y exclusividad de reserva.** Asegurar que cada ítem pertenece a las ventas autorizadas de la remisión o es stock libre asignable por ese actor. Dentro de una transacción, bloquear unidades en orden estable, verificar disponibilidad y registrar reserva. Diseñar unicidad de reserva activa compatible con MySQL —por ejemplo, una relación única de reserva vigente por unidad—, sin depender de un índice parcial de otro motor. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P04-04. Ciclo de documentos y relaciones.** Inventariar DELETE y CASCADE en facturas, ventas, usuarios, proveedores, recibos e inventario. Aplicar protección, desactivación o anulación según entidad; preservar documentos y datos históricos requeridos. No convertir todas las tablas indiscriminadamente a borrado lógico. Probar el resultado de eliminar entidades padre relacionadas. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P04-05. Identificadores escalables.** Retirar el generador aleatorio con solo 9000 valores por prefijo. Separar identidad estable y código visible, con unicidad y generación acotada/determinista. Mantener códigos ya impresos y búsquedas QR antiguas mediante identidad o alias preservados; no renumerar todo el inventario para resolver el problema. *(validada localmente 2026-10-02 — ver seguimiento.md)*

**Aceptación:** editar una factura conserva los mismos identificadores e historial; producto inválido no crea factura parcial; orden vacía o con cantidad cero falla; no se mezcla proveedor; factura pagada no se elimina; dos reservas simultáneas de una unidad producen una sola reserva activa. Permitir reservas simultáneas de unidades diferentes cuando sean válidas. PUT/DELETE de remisiones siguen bloqueados.

**Entrega:** reglas de transición, validadores, edición no destructiva, protección de relaciones y pruebas reales MySQL. La recepción comercial ampliada se completa en P11.

### P05 — Unificar estadísticas, costo, precios y fechas

**Cubre:** H13, H19, H24 y H31. **Dependencias:** base de pruebas P00 y contratos estabilizados; D03.

- [x] **P05-01. Reparto de ventas.** Crear cálculo reutilizable de participantes únicos antes de aplicar filtro personal; usar constantes válidas para estados. Excluir anuladas según cada reporte y evitar duplicar al vendedor principal entre compartidos. Aplicar la misma regla en dashboard, gráficos y reportes, manteniendo importes completos en listas/detalle. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P05-02. Costo integral único.** Calcular con Decimal base, telas/cueros y adicionales, distinguiendo cantidades unitarias y de grupo. Definir prioridad/migración de campos heredados para no omitir ni duplicar tela. Exponer el resultado del servidor a la interfaz y exportaciones. Documentar precisión y reparto de redondeos. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P05-03. Configuración de precios íntegra.** Garantizar exactamente un multiplicador general válido mediante configuración única y transición atómica compatible con MySQL. No permitir desmarcar/eliminar el único general sin sustitución. Ante configuración incompleta, bloquear la cotización/publicación afectada con error accionable; eliminar el respaldo silencioso a 1. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P05-04. Cambios de precios controlados.** Validar rangos de costos, metraje y multiplicadores sin romper cargos negativos legítimos. Añadir vista previa de alcance, autorización, versión e historial de cambios masivos, con restauración de versión anterior. Un cambio de precio actual no reescribe documentos aceptados. *(parcial: validación y bitácora; versiones/restauración pendientes)*
- [x] **P05-05. Tiempo de negocio.** Centralizar zona America/Bogota, instantes UTC, fecha local y período comercial del 6 al 5. Definir intervalos sin doble conteo en límites —inicio incluido y siguiente inicio excluido cuando proceda— y utilizarlos en caja, ventas, reportes y filtros. *(validada localmente 2026-10-02 — ver seguimiento.md)*

**Aceptación:** venta 300 entre tres atribuye 100 por persona y 300 a empresa; casos de uno/dos/más participantes, duplicados y anuladas; redondeos de importes no divisibles sin crear dinero. Costo 100 + 3 × 20 = 160 bajo la regla confirmada, tanto en API como UI. Quitar el único general falla o lo reemplaza atómicamente. Casos nocturnos, día 5/6 y diciembre/enero correctos.

**Entrega:** servicios puros de cálculo, pruebas por tabla de casos, glosario de importes y períodos; 21 pruebas de precios conservadas o adaptadas por un cambio de regla explícito.

### P06 — Migrar y conciliar datos sin perder historia

**Cubre:** H33, reparación asociada a H02–H15/H19/H20/H24 y conciliación de H32. **Dependencias:** escrituras corregidas P03–P05; respaldo recuperable; decisiones de datos.

- [x] **P06-01. Diagnóstico reproducible.** Crear comandos de solo lectura/dry-run para detectar pagos sin movimiento esperado, estados incompatibles, saldos incoherentes, reservas múltiples, identidades huérfanas, facturas descuadradas, costos duplicados/omitidos y permisos ambiguos. Mostrar conteos e IDs estrictamente necesarios con acceso restringido; no incluir datos personales en evidencia pública. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [ ] **P06-02. Fuentes de verdad.** Elegir la representación vigente para DetalleFactura/Inventario y telas heredadas/nuevas. Unificar Venta.sede con Sede mediante relación y mapeo explícito; conservar instantáneas históricas cuando correspondan. Registrar valores desconocidos para revisión, sin asignarlos a una sede inventada.
- [ ] **P06-03. Migraciones expansivas y por lotes.** Añadir primero campos/tablas compatibles, completar datos con comandos idempotentes y reanudables, verificar, cambiar lectores/escritores y retirar legado en una entrega posterior. Medir bloqueo y tiempo; planificar índices/restricciones conforme al MySQL real. No reescribir migraciones ya aplicadas para hacerlas coincidir con el nuevo modelo.
- [ ] **P06-04. Reparaciones trazables.** Proponer por cada inconsistencia causa, evidencia, corrección y reversión. No inventar un movimiento bancario/caja para hacer coincidir una suma ni reconstruir relaciones perdidas sin respaldo documental. Usar respaldos/eventos verificables; enviar casos ambiguos a revisión. Toda reparación aplicada conserva actor, motivo y lote.
- [ ] **P06-05. Ensayo y conciliación.** Ejecutar primero en datos sintéticos y después en copia autorizada/sanitizada representativa. Comparar conteos, importes, identidades, relaciones y permisos antes/después. Ensayar reejecución, interrupción y recuperación. Para datos reales, preparar aprobación concreta si no existe autorización vigente.

**Aceptación:** segunda ejecución sin duplicados ni cambios nuevos; todos los registros migrados o identificados como excepción pendiente; totales e identidades explicados; restricciones nuevas no se activan sobre datos inválidos inadvertidamente. Las excepciones materiales impiden cerrar el hallazgo afectado.

**Entrega:** informe de diagnóstico, plan de lotes, comandos de migración/conciliación, resultados y recuperación ensayada. Conservar compatibilidad hasta verificar los consumidores.

### P07 — Actualizar plataforma y hacer verificable la operación

**Cubre:** H18, H22, H23, H30 y H34. **Dependencias:** se prepara desde P00; el ensayo integral utiliza P01–P06.

- [~] **P07-01. Matriz de compatibilidad y dependencias.** Inventariar Python, Django, DRF, JWT, MySQL, Node y paquetes directos/transitivos. Consultar soporte y avisos oficiales vigentes al ejecutar; elegir versiones mantenidas compatibles, no congelar una recomendación temporal de este plan. Actualizar en pasos comprobables y fijar instalaciones reproducibles en ambos repositorios. Revisar usos de SheetJS y su distribución mantenida, incluidas exportaciones y lectura si existe. No ejecutar actualizaciones mayores automáticas sin analizar cambios incompatibles. *(parcial: paso A aplicado; Django 5.2 LTS ensayado, falta runtime del VPS)*
- [x] **P07-02. Auditoría automatizada.** Completar las revisiones de dependencias que fallaron por red en la auditoría original. Guardar fecha, versión del analizador, alcance y resultados sin inventar CVE. Priorizar por exposición real y soporte, documentar excepciones con responsable y revisión, y automatizar avisos periódicos. Analizar secretos sin imprimir sus valores. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P07-03. CI como requisito de entrega.** Ejecutar descubrimiento Django, regresiones de permisos/dinero/inventario, integración MySQL, comprobación de migraciones, sintaxis Python, lint JS/JSX, pruebas frontend y build. Añadir recorridos de extremo a extremo de operaciones críticas. Hacer fallar la entrega si una comprobación obligatoria falla; no convertirla en un aviso ignorado. *(parcial: workflows creados, sin ejecución en GitHub ni e2e)*
- [~] **P07-04. Despliegue que propaga errores.** Versionar dentro de los repositorios un procedimiento de releases por commit, con artefactos reproducibles y compatibilidad frontend/backend. Corregir manejo de fallos en el shell remoto: no ocultar instalación/migración detrás del éxito de tail. Verificar estado HTTP y contenido esperado del health check; un fallo de salud debe detener la publicación o activar recuperación controlada. *(preparada, no ejecutada contra el VPS)*
- [ ] **P07-05. Backups y recuperación ensayados.** Respaldar base, archivos subidos y configuración necesaria; cifrar, restringir acceso, guardar fuera del repositorio y del servidor, verificar integridad y retención. Restaurar en un entorno aislado y comprobar documentos, archivos, cuentas y conciliaciones. Medir tiempo real y pérdida recuperable frente a D08. Revertir código solo si el esquema y los datos son compatibles; una migración destructiva no se “arregla” cambiando el enlace de release.
- [x] **P07-06. Imágenes y correo fiables.** Crear validador compartido de imágenes con límite previo de bytes, cantidad, dimensiones y formato real; evitar lectura ilimitada y limpiar huérfanos mediante un proceso verificable. Registrar correo en una bandeja persistente dentro de la transacción del evento, procesar después del commit con reintentos, límites y estado visible. Separar “PQRS registrada”, “envío pendiente”, “enviada” y “fallida”; un fallo SMTP no debe fingir entrega. Evitar duplicados tanto como permita el proveedor y documentar el límite de entrega. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [~] **P07-07. Operación observable y documentación vigente.** Consolidar arranque/configuración/despliegue, sustituir README de plantilla, diagramar dominios y actualizar diccionario de estados/permisos. Mantener decisiones fechadas. Incorporar identificador de petición, registros estructurados sin secretos, salud/readiness sin datos sensibles, errores, latencia, conflictos financieros, cola fallida y edad del backup. Definir quién atiende cada alerta y cómo actuar. *(parcial: documentación de operación/contratos/permisos)*

**Aceptación:** versiones soportadas verificadas en fecha de implementación; instalación limpia desde locks; pruebas obligatorias verdes. Simular fallo de instalación, migración, salud, envío y restauración; comprobar código de salida y recuperación. Probar imagen inválida/sobredimensionada sin agotar recursos. Restauración utilizable con mediciones, no solo “backup creado”.

**Entrega:** CI, inventario de dependencias, runbook, evidencia de ensayo y release compatible. La configuración real del VPS/proxy se marca pendiente hasta inspeccionarla con acceso autorizado.

### P08 — Reducir cargas y unificar la experiencia de trabajo

**Cubre:** H25, H26, H29; U02–U08/U10 y preparación de U09. **Dependencias:** contratos estables y D05.

- [x] **P08-01. Medir antes de optimizar.** Construir datos sintéticos representativos de volumen y distribución. Medir consultas, tamaño de respuesta, latencia mediana/p95 y tiempos percibidos de inventario, facturas, ventas y selectores. Registrar hardware/concurrencia y acordar presupuestos. No afirmar una mejora sin comparar condiciones equivalentes. *(hecho: `medir_rendimiento` sobre la copia de producción, antes/después en `evidencia/p08-*`; datos sintéticos 2 vs 6 filas en `test_rendimiento`; presupuestos **provisionales** D05)*
- [~] **P08-02. Paginación y búsqueda completas.** Definir contrato consistente, orden estable con desempate, límites de tamaño, filtros y búsqueda en servidor. Cambiar clientes/proveedores a autocompletado paginado que alcance registros más allá de la primera página. Recorrer catálogos completos solo cuando sean pequeños y sea explícitamente necesario. Coordinar cambio de forma de respuesta con consumidores existentes. *(parcial: proveedores completos y búsqueda en servidor; recorrido por número de página; orden estable en ordenes-pedido; inventario sin paginar)*
- [~] **P08-03. Cargar solo lo necesario.** Quitar la descarga inicial seguida de todas las facturas con full=true; pedir detalle al abrirlo. Crear agregados para totales del conjunto filtrado y exportaciones dedicadas, con procesamiento en segundo plano cuando el volumen lo requiera. Aplicar los mismos filtros y permisos en pantalla/exportación; una exportación no se limita por error a la página visible. *(parcial: sin descarga full=true en facturas; exportaciones de caja/recibos/egresos/clientes completas con los mismos filtros; inventario completo y agregados pendientes)*
- [~] **P08-04. Consultas y contratos mantenibles.** Completar select_related/prefetch_related y filtros; añadir índices a partir de planes/mediciones, cuidando costo de escritura. Extraer servicios de dominio de vistas y serializadores grandes. Definir OpenAPI o contratos equivalentes y tipos graduales en límites de API; no imponer una conversión completa de archivos como condición para corregir fallos. *(parcial: N+1 de grupos, facturas full, subcategorías y órdenes con prueba de consultas constantes; contratos en `contratos-api.md`; índices y OpenAPI pendientes)*
- [~] **P08-05. Estado frontend por dominio.** Centralizar API en servicios, consultas/mutaciones en hooks React Query y claves que incorporen filtros y alcance de permisos/usuario. Invalidar solo lo necesario después de cambios y limpiar cachés sensibles al salir/cambiar de usuario. Dividir páginas en tabla, filtros, formularios, detalle e impresión; retirar listas de servidor de AppContext. *(parcial: caché de React Query se limpia al salir; clientes retirados de AppContext)*
- [~] **P08-06. Formularios resistentes.** Añadir borradores con versión y dueño, recuperación después de sesión/red y expiración/limpieza segura. No persistir tokens ni datos sensibles innecesarios en borradores. Mapear errores a campos/filas, mantener valores y distinguir validación, permiso, conflicto y conexión. Avisar al cerrar solo si hay cambios sin guardar; una repetición de envío utiliza idempotencia. *(parcial: borradores con versión/dueño/expiración en Nueva Venta y Factura de Proveedor; errores del servidor legibles y clasificados en toda la app; idempotencia en venta.crear y factura.crear; falta mapear errores a campos/filas en la UI)*
- [~] **P08-07. Componentes y accesibilidad comunes.** Converger a un modal con nombre accesible, foco inicial, confinamiento/devolución de foco, teclado y cierre coherente con cambios pendientes. Reutilizar estilos existentes. Unificar toasts y cargas locales con anuncios accesibles, tiempo suficiente y detalle recuperable. Verificar etiquetas, nombres de iconos, contraste y navegación por teclado en caja, ventas y bodega. *(parcial: comportamiento de diálogo común con foco/Escape/descarte en ambos Modal y en los modales propios de inventario, caja, telas, referencias, facturas y pedido de materiales; toasts accesibles con anuncio y pausa; falta el recorrido de teclado y contraste de U07)*
- [~] **P08-08. Tablas y acciones comprensibles.** Persistir filtros en URL, homogeneizar rangos/orden, ofrecer columnas y totales filtrados. Mostrar acciones según permiso/estado y explicar bloqueos cuando sea útil. La UI nunca sustituye la validación de servidor. No revelar por un botón o mensaje información de objetos ajenos. *(parcial: filtros persisten en la URL y totales del conjunto filtrado en caja, recibos, egresos, ventas, inventario y facturas; faltan columnas/exportación coherentes y acciones según estado)*
- [x] **P08-09. Impresión consistente.** Reutilizar plantillas y formateo de importes/fechas, incluir versión del documento, controlar saltos/páginas y textos largos. Mantener “Pagado” en PDF de egreso y explicar su semántica al operador. Probar costos ocultos, datos escapados, varios productos y varias páginas; la impresión no altera estado. *(validada localmente 2026-10-02 — ver seguimiento.md)*

**Aceptación:** proveedor/cliente 103 localizable; ninguna pantalla descarga todo el inventario por defecto; filtros y totales coinciden entre lista y exportación; mediciones cumplen presupuesto acordado. No se pierden formularios ante errores; no aparecen borradores/cachés del usuario anterior; teclado y modal operables; impresión extensa legible sin contenido ejecutable.

**Entrega:** mediciones antes/después, contratos, componentes comunes y recorridos de escritorio/tablet/teléfono. El expediente se completa en P09 y la operación móvil de bodega en P11.

### P09 — Construir cotizaciones persistentes y ventas con líneas

**Cubre:** F01, F02, inicio de F03/F11 y U01. **Dependencias:** G1/G2, P08; D03 y alcance comercial acordado.

- [x] **P09-01. Cotización del servidor.** Crear documento con número, cliente, asesor, vigencia, estado, versión y líneas. Guardar cantidades, variante, telas/opciones, precio aceptado, descuento autorizado y versión de cálculo. Acceso por objeto/rol, borradores y control de edición concurrente. Separar cotización provisional de una aceptada con instantánea preservada. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P09-02. Migrar el carrito con cuidado.** Sustituir la clave compartida lp_cotizacion_cart por borradores asociados al usuario. No atribuir automáticamente un carrito antiguo de dueño desconocido al siguiente usuario del navegador. Ofrecer recuperación identificada al usuario autorizado; limpiar caché al cambiar sesión y evitar duplicados de conversión. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P09-03. Venta con líneas propias.** Modelar cantidad, producto/variante, especificaciones, precio, descuento y compromiso de entrega por línea. Relacionar compras, reservas, recepción y remisiones con esas líneas, conservando el creador real de cada orden. Derivar totales en servidor y guardar las instantáneas comerciales necesarias. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P09-04. Convertir sin redigitar.** Convertir cotización aceptada a venta en una operación autorizada, atómica e idempotente. Definir si una cotización permite una o varias conversiones parciales antes de implementarlas; usar el alcance más simple acordado. No recalcular silenciosamente un precio ya aceptado al cambiar el catálogo. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P09-05. Expediente de venta.** Mostrar cotización, compromisos, pagos, saldo, compras, telas, inventario, recepción, remisiones, novedades, responsable y siguiente acción. Construir la línea de tiempo desde eventos y vínculos verificables, filtrada por permisos. Evitar solicitudes por cada fila y costos visibles a roles no autorizados. *(validada localmente 2026-10-02 — ver seguimiento.md)*
- [x] **P09-06. Compatibilidad de ventas históricas.** Enlazar líneas donde los datos lo demuestren; marcar cabeceras heredadas pendientes de detalle cuando no sea posible. No inventar productos o compromisos para completar el esquema. Mantener consulta/cobro de documentos anteriores y conciliación de sus totales. *(validada localmente 2026-10-02 — ver seguimiento.md)*

**Aceptación:** cotización persiste entre sesiones/dispositivos autorizados, no se filtra entre usuarios y conserva precio aceptado; conversión repetida crea un único resultado conforme al contrato. Venta de varias líneas tiene total conciliado y vínculos estables; expediente permite seguir una operación sin reconstruirla manualmente.

**Entrega:** primer flujo cotización→venta→compra/reserva trazable. F03 se cierra después de comprobar recepción y entrega en P11.

### P10 — Completar cartera, proveedores, conciliación y cajas por turno

**Cubre:** F05, F06, F07, F08 y cierre funcional de H32. **Dependencias:** P03/P06/P09; D02 y D08.

**Estado de la fase (2026-10-06): no terminada.** Validadas en local: P10-03 completa; P10-01, P10-02, P10-04 y P10-05 parciales. Lo que falta depende sobre todo de decisiones del negocio: D02 (descuentos por pronto pago, anticipos, sobrepagos), D10g (programación de pagos, provisional), quién autoriza ajustes de diferencias de caja y el bloqueo/reapertura de períodos (D08).

**Ajuste de alcance confirmado por el usuario (2026-10-02):** ninguna fecha hace que una venta quede vencida, y existe una sola caja en una sede. No implementar mora/antigüedad 30/60/90 como deuda vencida ni un reparto de efectivo entre sedes. Ver D10a–D10d en decisiones.md. Las fechas de promesas sirven únicamente para seguimiento.

- **P10-01. Cartera por aplicaciones.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borraron la pantalla Cartera, su API y PromesaPago.
- **P10-02. Cuentas por pagar.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borraron Cuentas por pagar, los abonos parciales (AplicacionEgreso, estado «pago parcial») y la programación de pagos. Se conserva la corrección D10f: pagar no pisa `fecha_pago` (fecha límite) y la fecha real queda en `fecha_pago_real`.
- **P10-03. Conciliación bancaria.** — **Retirada del alcance por el nuevo prompt (2026-10-08, D16). No recrear Bancos.** Código eliminado; eliminación física de sus tablas pendiente de autorización de revisión automática. Ver P16-02.
- **P10-04. Turnos de la caja principal.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borraron Turnos de caja (TurnoCaja, `Caja.turno`); Caja vuelve a su «Cierre de Caja» clásico.
- **P10-05. Conciliación continua y períodos.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borraron la pantalla Conciliación y su API. Bancos también se retira por D16 (2026-10-08); ver P16-02.

**Continuación después de la entrega del 2026-10-06:**

1. Conservar `ordenes/conciliacion.py` como consulta: diferencias históricas, ausencia de vínculos y descuentos no autorizan generar pagos ni corregir balances. La evidencia incluye todos los registros enlazados, aunque estén fuera de las fechas del documento padre.
2. Resolver D02 con contabilidad antes de activar pagos parciales/anticipos, descuentos y sobrepagos. Implementar aplicaciones explícitas en P10-02; la FK histórica factura→comprobante y el importe completo del egreso no representan aplicaciones individuales. Añadir casos de varias facturas y varios pagos por factura antes de migrar historia. *(Hecho en local: aplicaciones explícitas `AplicacionEgreso` y abonos parciales (D10f). Sigue pendiente D02 para descuentos, anticipos y sobrepagos.)*
3. Acordar quién autoriza las diferencias de caja y qué operaciones bloquea un período cerrado. Después implementar ajustes vinculados e inmutables, separación de permisos, idempotencia y carreras MySQL. No reutilizar el reporte de lectura como una ruta de escritura ni sobrescribir cierres.
4. Bancos y reportes de conciliación están fuera del alcance actual (D16/D-ALCANCE). No reintroducirlos.
5. Ensayar activación con los permisos descritos en `matriz-permisos.md` y `operacion.md`. No conceder los nuevos permisos automáticamente ni dar P10 por terminada hasta probar los pendientes y el flujo completo en staging.

**Aceptación:** casos de pago parcial, anticipo, sobrepago permitido, descuento, reversión y factura anulada producen saldos explicables bajo D02. Importar dos veces un extracto no duplica líneas; conciliación errónea se revierte con historia. Dos operadores no cierran/aplican el mismo turno dos veces. Estado de cuenta y contabilidad operativa derivan de las mismas aplicaciones.

**Entrega:** tableros y estados de cuenta conciliados, acciones autorizadas y reglas explicadas. Cualquier conexión bancaria real o transferencia externa queda fuera hasta autorización específica.

### P11 — Completar recepción, disponibilidad y entrega comprobable

**Cubre:** F03, F04, F09, F10 y U09. **Dependencias:** P04/P06/P09, idempotencia y contratos; D04.

**Estado de la fase (2026-10-06): en curso.** D04 y D04b confirmados por el usuario: inventario por unidad y por grupos (comedor, alcoba), la factura llega con la mercancía (factura = recepción) y la entrega se confirma de forma simple, por quien esté disponible. Validadas en local: P11-01, P11-02, P11-03 y P11-04 completas; P11-05 parcial (solo espera la prueba en iPhone real con https). Siguiente: probar en un iPhone real la cámara y el flujo de entrega (P11-05; ver la guía en operacion.md → P11). Al retomar, leer las filas P11 de [seguimiento.md](seguimiento.md) y la sección P11 de [operacion.md](operacion.md).

- [x] **P11-01. Recepción parcial vinculada.** Crear recepciones contra líneas de compra con cantidades recibidas/rechazadas/pendientes, responsable y evidencia. Registrar faltantes, diferencias y devoluciones al proveedor. Comparar pedido↔recepción↔factura y derivar inventario de eventos identificables; evitar doble generación al facturar mercancía ya recibida. *(completa en local: la factura es la recepción (D04b); cada fila se liga a la línea de la orden de pedido, lo pendiente se deriva de las unidades ligadas, no se recibe más de lo pedido (bloqueo de línea) y la orden pasa sola a recibido; devolución al proveedor de una unidad ya recibida (la línea vuelve a quedar pendiente, P11-02); rechazos al recibir con cantidad, motivo y responsable —lo rechazado no se factura y la línea sigue pendiente para la reposición—; sin evidencia fotográfica: no acordada)*
- [x] **P11-02. Separar condición y disponibilidad.** Distinguir ubicación/estado físico de reserva comercial, tránsito, reparación, devolución y consignación según alcance acordado. Registrar movimientos con origen/destino/motivo/documento/actor; derivar disponibilidad sin contar mercancía reservada dos veces. Añadir conteos cíclicos y ajustes autorizados con diferencias. *(validada en local 2026-10-06: `MovimientoInventario` con antes/después, actor, motivo y documento en factura, edición, traslado, remisión (reserva/despacho/entrega/liberación), devolución al proveedor y conteo; disponibilidades de proceso (por despachar, despachado, devuelto al proveedor) no se ponen a mano y una unidad en remisión activa no cambia por edición (D04c); conteos cíclicos por zona con faltantes/sobrantes y ajuste con AJUSTAR_INVENTARIO. Sin migrar datos: 'por_reparar' sigue existiendo como disponibilidad y como estado físico, y 58 unidades tienen estado físico 'nuevo' fuera del catálogo)* *(2026-10-06: la parte de conteos cíclicos se eliminó por decisión del usuario, D-ALCANCE; quedan movimientos, devolución al proveedor y disponibilidad protegida)*
- [x] **P11-03. Entrega por línea y cantidad.** Relacionar remisión, unidades o cantidades, venta y destino. Mostrar preparado/despachado/entregado/pendiente, permitir parciales y registrar evidencia acordada de recepción —firma, foto o constancia—, novedad, devolución y reasignación. Nunca reabrir disponibilidad de mercancía aún en tránsito por un simple cambio de etiqueta. *(completa en local: confirmación simple como constancia (D04); al confirmar se declara por producto/cantidad lo no entregado con motivo, vuelve a bodega y se sugiere en la siguiente remisión; la venta no se cierra con pendientes; confirmación bloqueada contra dobles cierres; la vista móvil es P11-05, que en local ya cubre al transportador en su celular y solo espera la prueba en iPhone real)*
- [x] **P11-04. Flujo completo y responsables.** Comprobar el recorrido cotización→venta→compra/reserva→recepción→preparación→despacho→entrega con los mismos identificadores y un responsable por transición. Documentar cancelaciones, entrega parcial, sustitución autorizada y reintento de cada operación. *(validada en local 2026-10-06: `suministros/tests/test_flujo_completo.py` recorre cotización → venta → orden de pedido ligada a la línea de venta → dos facturas parciales → remisión → despacho → entrega parcial → segunda remisión confirmada por la oficina → venta entregada, con el responsable de cada paso; cancelación, sustitución y reintento documentados en operacion.md → P11)*
- [~] **P11-05. Interfaz móvil de bodega/transporte.** Implementar QR, botones amplios, formularios breves, confirmación clara y estado de conexión. Probar cámara/permisos, códigos antiguos, duplicados de escaneo y mala conectividad en dispositivos acordados. Si se incluye operación sin conexión, almacenar acciones pendientes por usuario/dispositivo, mostrar que aún no están confirmadas y sincronizar con idempotencia y resolución explícita de conflictos; nunca anunciar éxito antes de aceptación del servidor. *(parcial, en local: pantalla Conteos usable en teléfono: campo grande para QR/código (lector tipo teclado o escrito), lector QR con la cámara para iPhone (jsQR) y Android (BarcodeDetector) con mensajes de permiso, estado de conexión, "Enviando… (aún no confirmado)" hasta la respuesta, escaneo repetido sin duplicar; en Remisiones, verificación opcional con QR al despachar y al entregar (avisa productos que no van) y reintento de la confirmación sin duplicar. Sin cola sin conexión (no acordada). Falta solo la prueba en iPhone real, que requiere https: hacerla tras desplegar o con un túnel, con la guía de operacion.md → P11)* *(2026-10-06: la pantalla Conteos se eliminó por decisión del usuario; el lector QR queda solo en la verificación de remisiones)*

**Aceptación:** recibir 2 de 3 deja 1 pendiente; facturar después no duplica inventario; entregar parcialmente conserva pendientes y evidencia. Cancelación/devolución libera o mueve solo lo que corresponda. Dos transportadores no entregan dos veces la misma unidad. Repetición de escaneo/reconexión no duplica eventos ni reservas.

**Entrega:** trazabilidad completa, pruebas de cantidades, conciliación de stock y validación móvil con cada rol.

### P12 — Aportar margen, comisiones, posventa y excepciones accionables

**Cubre:** F11, F12, F13 y F14. **Dependencias:** P05/P09 y datos de P10/P11; D03.

- [x] **P12-01. Precio y margen explicables.** Completar versión de tarifa, descuento autorizado, costo integral y margen por línea/grupo/venta. Diferenciar margen estimado al vender y costo real posterior según política acordada; preservar ambas referencias cuando sea necesario. Mostrar impacto de multiplicadores antes de publicar y restringir acceso a costos/márgenes. *(completa en local 2026-10-06: tope de descuento estándar 25% y configurable por variante `VarianteProducto.descuento_maximo`; validación ponderada en cotizaciones y por línea en ventas; costo estimado congelado `costo_lista` en `LineaCotizacion` y `LineaVenta`; prorrateo proporcional de descuentos al convertir cotización a venta garantizando Σ subtotal == venta.valor_total; protección estricta en DRF con mixin `SinMargenSinPermisoMixin` para que solo administradores o usuarios con `VER_MARGENES` vean costos y márgenes; simulación de impacto de multiplicador antes de aplicar con `POST /api/listaprecios/multiplicadores/<id>/simular/` y vista interactiva en React)*
- [x] **P12-02. Comisiones por versión y período.** *(2026-10-06: reemplazada por **Nómina** según las reglas del usuario (D12a): comisión 3–4 % según el descuento sobre el precio de lista, pagadera con abono ≥ 30 %; bonificación del 1 % por meta, pagada desde el cierre siguiente al entregar; básico (día 20); ajustes +/-; pendientes arrastrados entre cierres; todo editable en borrador; exportación a Excel con cierre general y hoja por asesor. Validada en local: `ordenes/nomina.py`, `/api/nomina/…`, `test_nomina.py` (7) y `NominaPage.test.jsx` (3), con un ensayo revertido sobre las ventas reales de septiembre (102 ventas, 10 asesores, 23 consultas). El modelo anterior de reglas, períodos y liquidaciones se borró (migración `ordenes 0050`))*
- **P12-03. Posventa ligada al producto.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borraron Posventa y Garantías, sus evidencias privadas y «Escalar a posventa» en PQRS.
- **P12-04. Tablero de excepciones.** — **fuera del alcance actual: eliminado por decisión del usuario (2026-10-06, D-ALCANCE). No implementar.** Se borró el tablero de Excepciones.

**Aceptación:** cada cifra puede explicarse hasta documento/versión; cambios de tarifa no alteran contratos anteriores. Comisión puede recalcularse con el mismo resultado para la misma versión; devolución se refleja como ajuste identificable. Caso de posventa llega a responsable y resolución. Las excepciones desaparecen o cambian al resolver su causa y respetan filtros/permisos.

**Entrega:** reportes trazables y pruebas con escenarios representativos revisados por responsables comerciales/operativos.

### P13 — Integración contable/fiscal y calidad de datos

**Cubre:** F15 y F16. **Dependencias:** contratos/documentos estables; D06.

**Alcance confirmado el 2026-10-06 (D06a):** el usuario usa **SIIGO** y **no necesita exportaciones ni conexión con SIIGO por ahora**. P13-02 queda fuera del alcance actual, sin declararlo implementado. Esto no elimina la revisión de permisos y conservación de datos de P13-04. Inventario y continuación: [alcance-contable-y-calidad.md](alcance-contable-y-calidad.md).

- [~] **P13-01. Definir cobertura real.** Inventariar sistemas contables, facturación de ventas, responsabilidades y flujo documental existente. Acordar qué se exporta o integra, catálogo de conceptos, identificadores, estados y tratamiento de fallos. FacturaProveedor no demuestra cobertura de facturación fiscal de ventas. Verificar requisitos actuales con fuentes oficiales y responsables pertinentes antes de implementar reglas normativas. *(parcial 2026-10-06: decisión SIIGO/sin intercambio confirmada e inventario de documentos del código registrado. Responsables, emisión fiscal y correspondencia ERP–SIIGO no se han verificado; no son motivo para implementar ahora un adaptador no solicitado).*
- **P13-02. Adaptador desacoplado e idempotente — fuera del alcance actual por D06a.** Si se solicita intercambio en el futuro, implementar el alcance acordado —exportación o integración— mediante un adaptador, bandeja persistente, identificador externo, reintentos, trazabilidad y conciliación. Probar en sandbox, con fallos y respuestas repetidas. No emitir, anular ni enviar documentos fiscales reales por una prueba. La decisión explícita de no integrar por ahora está registrada; no hay adaptador SIIGO implementado.
- [~] **P13-03. Calidad de maestros.** Normalizar teléfonos/direcciones sin destruir el valor original útil; detectar candidatos a cliente duplicado con reglas explicables. Vista previa de fusiones y selección autorizada; preservar referencias, historia y datos comerciales de los documentos. No fusionar automáticamente personas distintas por coincidencia parcial. *(parcial validada localmente 2026-10-06: módulo `/calidad-clientes` con correcciones de formato seleccionadas individualmente, originales en `CorreccionCliente` —migración 0047—, autor/fecha, versión firmada, bloqueo, idempotencia y permisos explícitos. Candidatos explicados por documento o nombre+contacto, comparación de conflictos y ventas visibles. 22 pruebas de dominio/API, 1 carrera MySQL y 8 de interfaz. **Falta la fusión ejecutable**: conservar identidad histórica de todos los documentos, resolver conflictos con selección humana, definir la ficha resultante y validar cada relación; la comparación actual no traslada ni borra registros).*
- [~] **P13-04. Exportación, acceso y conservación.** Definir campos por rol, filtros, trazabilidad de descarga y formatos coherentes. Tratar contenido de texto potencialmente interpretable como fórmula en hojas de cálculo según formato. Definir retención, anonimización/eliminación permitida y atención de solicitudes conforme a D06, respetando documentos que deban conservarse. Probar que exportaciones/adjuntos no abren rutas alternativas de acceso. *(parcial validada localmente 2026-10-06: XLSX de clientes generado y auditado por el servidor, con permiso existente `EXPORTAR_CLIENTES`, campos explícitos y clientes de ventas visibles; historial comercial sin ventas ajenas, notas por alcance; comisiones y CSV con alcance personal/global coherente, tasas ajenas ocultas y edición genérica protegida. Límite explícito de 10 000 filas, rechazo sin archivo parcial, texto literal XLSX/CSV y errores visibles en UI. Auditoría acredita generación del archivo, no recepción efectiva. 29 regresiones backend y 9 de interfaz. Restan otras salidas/adjuntos, D06d y conservación D06b).*

**Desglose verificable de P13-03:**

- [x] Vista previa de correcciones de formato, con selección explícita de campos y sin modificar el documento de identidad.
- [x] Historial con valores originales, valores corregidos, usuario y fecha (`CorreccionCliente`, migración 0047).
- [x] Candidatos a duplicado con criterios explicados y comparación de conflictos entre dos fichas.
- [x] Permisos y alcance por cliente, versión de la vista previa, escritura atómica e idempotencia; rechazo de cambios simultáneos incompatibles.
- [x] Interfaz integrada en menú y rutas; 22 pruebas de dominio/API, 1 de concurrencia MySQL y 8 de interfaz validadas localmente.
- [ ] Fusión ejecutable con resolución humana de conflictos, preservación de identidad histórica y de todas las referencias, auditoría y pruebas de concurrencia/recuperación de la fusión.
- [ ] Validación del módulo con operadores en staging, escritorio y móvil, junto con P14; la suite de interfaz actual usa jsdom.

**Desglose verificable de P13-04:**

- [x] Clientes: exportación XLSX del filtro completo dentro del alcance comercial, permisos comprobados en API, campos explícitos sin historia/ventas y límite visible sin truncamiento.
- [x] Historial comercial: ventas propias/compartidas con permiso de ventas; lectura y mutación de notas limitadas al cliente visible; explicación de alcance en escritorio y móvil. Directorio básico y edición vigente preservados provisionalmente (D06d).
- [x] Comisiones: liquidaciones, totales, conteos, tasas específicas y CSV coherentes con alcance personal/global; `PUT/PATCH` exige gestionar y rechaza períodos cerrados.
- [x] Auditoría de generación de XLSX/CSV sin copiar clientes ni búsquedas personales; XLSX tipado como texto y CSV neutralizado sin convertir importes negativos a texto; errores y estado de descarga en interfaz.
- [x] Regresiones locales de permisos, alcance, filtros, límites, fallos de auditoría, contenido de archivos y doble clic; suites completas MySQL/SQLite/frontend correctas.
- [ ] Revisar exportaciones de ventas, recibos, egresos e inventario, impresión y todos sus caminos de acceso; inventario en `exportaciones-y-datos.md`.
- [ ] Revisar evidencias de posventa y otros adjuntos, incluidos URL y almacenamiento directo; demostrar controles con pruebas negativas.
- [ ] Confirmar D06d y comprobar todas las rutas de creación/edición de clientes conforme a la política acordada.
- [ ] Definir responsable, conservación, solicitudes y anonimización/eliminación autorizada (D06b); no hay purgas implementadas.
- [ ] Validar descargas y permisos efectivos en navegador real/staging con operadores (P14).

**Aceptación:** exportación/integración acordada concilia documento por documento; reintentos no duplican efectos externos; falla visible y recuperable. Fusión de prueba conserva todas las relaciones y puede auditarse. Rol limitado no exporta costos ni datos ajenos. Reglas de conservación registradas sin afirmar certificación legal no realizada.

**Entrega:** decisión de alcance, adaptador o exportación validada, procedimientos de calidad y política operativa de datos.

### P14 — Aceptación integral y cierre de cobertura

**Cubre:** verificación de todos los elementos del informe. **Dependencias:** fases aplicables completadas y decisiones registradas.

- [x] **P14-01. Recorridos integrales por rol.** Probar vendedor principal/compartido, auxiliar, bodega, transportador, aprobador y administrador con los roles reales configurados. Cubrir compra para cliente y stock, contado/transferencia, parcial, anulación, devolución, costo restringido y documento histórico. *(validada en local 2026-10-06 por la API con la foto de permisos reales de la copia (`ordenes/tests/roles_reales.py`): `test_recorridos_por_rol.py` (vendedor principal/compartido, auxiliar compras/bodega/caja, transportador, administrador aprobador; compra para cliente y stock, contado/transferencia, parcial, anulación, devolución, costo restringido, documento histórico, pantallas nuevas por permiso), más `test_flujo_completo` y `test_aceptacion_integral`. Hallazgos de configuración R1–R5 en [aceptacion-y-publicacion.md](aceptacion-y-publicacion.md). En navegador con operadores: P14-03)*
- [~] **P14-02. Condiciones adversas.** Ejecutar doble clic, solicitudes concurrentes, timeout tras commit, dos pestañas, sesión expirada, cambio de permisos, fallo externo, caída de worker, migración interrumpida y recuperación de backup. Verificar que no se pierden datos ni se duplican efectos. *(parcial, en local 2026-10-06: matriz condición → prueba en aceptacion-y-publicacion.md §2; corregida la expulsión de sesión con dos pestañas tras la rotación de tokens; respaldo de la copia restaurado y migrado en MySQL desechable con conteos idénticos. Pendiente con el VPS: caída real de worker, corte de red con la base y restauración en el servidor)*
- [~] **P14-03. Aceptación con operadores.** Preparar datos ficticios y guiones por función. Observar escritorio y dispositivos acordados; resolver problemas materiales de accesibilidad/usabilidad. Actualizar guías breves de caja, aprobación, inventario, entrega y recuperación de formularios. *(guiones por función listos en aceptacion-y-publicacion.md §3, con iPhone; pendiente ejecutarlos con los operadores)*
- [~] **P14-04. Publicación gradual autorizada.** Definir responsables, versión de ambos repositorios, migraciones, señales de salud, interrupción/retorno y comprobaciones posteriores. Cuando exista autorización, publicar y verificar conciliaciones y métricas. No describir una prueba local como despliegue completado. *(plan de publicación gradual por permisos en aceptacion-y-publicacion.md §4: backend compatible con el frontend actual, luego frontend, luego activación por semanas; pendiente tu autorización y decidir cómo agrupar los commits)*
- [~] **P14-05. Cierre documentado.** Completar matrices siguientes con pruebas y estado real. Entregar resumen de cambios, decisiones, riesgos residuales, operación y próximos responsables. Toda mejora retirada por decisión explícita queda como cambio de alcance visible; no como implementada. *(borrador de riesgos residuales en aceptacion-y-publicacion.md §5; se cierra después de publicar y ejecutar P14-03)*

**Aceptación final:** todas las tareas del alcance acordado tienen evidencia, las reglas originales siguen funcionando, no quedan hallazgos materiales abiertos sin comunicar y la recuperación está demostrada en el entorno indicado.

### P15 — Productos de la venta, operación bajo pedido y nómina exacta

Ampliación expresa del usuario posterior a D12a. Dependencias: líneas de venta P09, recepción/remisiones P11 y Nómina actual; no requiere recuperar los módulos retirados por D-ALCANCE.

- [~] **P15-01. Desglose completo y editable de la venta.** El auxiliar registra cabecera y el asesor principal/compartido completa productos sin cambiar importes de la cabecera sin permiso. Catálogo completo y búsqueda paginada, variante, cantidad, tela, opcionales, adicionales y referencias comerciales; artículos especiales con valores explícitos y motivo. Borrador y confirmación del desglose, control de versiones, idempotencia y auditoría.
- [~] **P15-02. Precio de lista verificable.** Reutilizar el motor del catálogo incluyendo costos base/tela, cargos fijos/opcionales, multiplicador y precios manuales vigentes; conservar una instantánea por línea y motivo de cualquier ajuste. Separar precio de lista del precio pactado. Un cambio posterior del catálogo no revaloriza ventas/documentos históricos. No inventar precios históricos faltantes.
- [~] **P15-03. Pedidos rápidos por proveedor.** Vista previa desde líneas pendientes, selección de proveedor/referencia, cantidades parciales y texto editable del pedido; conservar vínculo y autor. No duplicar unidades ya pedidas al reintentar; no inferir asociaciones por nombre ambiguo. Permitir varios pedidos/documentos asociados sin confundir producto vendido y pedido.
- [~] **P15-04. Recepción y despacho con datos precargados.** Facilitar factura desde pedido y recepción parcial; conservar identidad de la línea hasta inventario/remisión. Texto de cliente independiente del de proveedor, editable al preparar entrega, y cantidades pendientes verificadas por servidor. Stock opcional sin asignar unidades ajenas ni duplicar reservas.
- [~] **P15-05. Nómina basada en precio de lista completo.** Total de lista a partir de líneas confirmadas; tabla/abono mínimo/metas y reparto D12a. Una venta sin precio suficiente debe indicar revisión pendiente, sin presentarse como comisión exacta al 0 % de descuento. Conservar valores manuales históricos identificados y ajustes autorizados; los cierres cerrados no cambian al editar catálogo o venta.
- [~] **P15-06. Aceptación integral y documentación.** Casos de tela/opcionales/cargos negativos legítimos, artículo especial, conjunto de productos, venta compartida, descuentos, entregas/recepciones parciales, reintentos/concurrencia, historial y permisos. Preparar guion por auxiliar/vendedor/compras/bodega/nómina y registrar qué validó el agente y qué necesita al usuario. Actualizar siempre este plan.

Avance en curso (corte 2026-10-07): editor comercial y catálogo paginado; cálculo congelado, excepciones autorizadas; pedidos por proveedor y pendientes; vínculo explícito de pedidos históricos; accesos a recepción/remisión; stock opcional; y origen del precio en Nómina implementados. La migración expansiva `0051_lineanomina_origen_precio_and_more.py` ya fue aplicada en la base MySQL de pruebas real `u756180748_pruebasv3`; no se aplicó en producción. Las pruebas automatizadas siguen usando bases desechables/fixtures aisladas cuando corresponde, pero la verificación de carga de la plataforma se hizo con registros existentes de la base de pruebas y no se sembraron datos ficticios allí. Falta aceptación de operadores, recorrido de guardado con datos reales, revisión visual de recepción/remisión, ejecutar el conjunto MySQL completo y decidir la publicación. No marcar despliegue ni aceptación operativa como terminados.

**Rediseño pedido por el usuario el 2026-10-07 (D15a):** los productos se ven y editan dentro de la venta expandida, sin ventana superpuesta ni línea de tiempo/alerta; precio global (sin precio unitario ni descuento por producto: el descuento se calcula con los precios de lista), fecha de entrega solo de la venta, sin especificaciones (texto proveedor —o "No aplica"— y texto cliente/remisión), referencia de compra sugerida automáticamente. Migración `ordenes 0052` aplicada en `pruebasv3`. Calidad de clientes pasó a pestaña de Bases de datos (D06c-b). **No volver a poner precio unitario, descuento, fecha ni especificaciones por producto.**

**Incidente de carga reportado el 2026-10-07:** el error `500` se produjo porque la base de pruebas real no tenía la migración `0051`. Ya fue aplicada en esa base y el backend local responde correctamente a `/api/user/`, `/api/ventas/`, pedidos y nómina con datos existentes. El escenario ficticio queda limitado a pruebas automatizadas y no se usa como fuente del frontend. El código P15 sigue sin commit/publicación desde este árbol; antes de desplegar hay que sincronizar ambos repositorios, ejecutar las migraciones pendientes en el entorno autorizado, reiniciar el backend y comprobar `/api/user/` y `/api/ventas/` autenticados. No se ejecutó ninguna acción en producción.

## 6. Matriz completa de cobertura

Las columnas de evidencia describen **lo que el agente deberá demostrar**; no son resultados de una implementación ya realizada. Todos los elementos están inicialmente pendientes. Registrar el avance en seguimiento.md sin modificar la fotografía de informe.md/resultados.json.

### Hallazgos técnicos

| ID del informe | Mejora y tareas responsables | Evidencia mínima para cerrar |
|---|---|---|
| H01 | Secretos: P01-01, P01-03, P01-04 | Accesos afectados rotados/revocados con autorización; lugares expuestos saneados y prevención activa; alcance histórico/remoto declarado |
| H02 | Caja: P03-02, P03-03 | Importe negativo, cierre genérico y saldo insuficiente rechazados; saldo calculado y carreras controladas |
| H03 | Atomicidad: P03-01 | Fallos inyectados antes de completar cada escritura dejan cabeceras/líneas/saldos/estados como estaban |
| H04 | Identidad de inventario: P04-01 | Edición conserva PK/QR, telas, costos, reservas e historial |
| H05 | Objeto y campos: P02-01 | Edición de venta ajena y cliente sin permiso fallan sin cambios |
| H06 | Datos restringidos: P02-01, P02-02 | Rutas alternativas y exportaciones tienen el mismo alcance; costos ausentes para el rol restringido |
| H07 | Aprobación: P02-02, P03-04, P03-07 | CRUD no confirma; acción autorizada registra aprobación/reversión y efectos únicos |
| H08 | Acciones de precios: P02-02, P05-04 | Lectura no permite asignar multiplicador; cambio masivo con vista previa, historia y restauración |
| H09 | Cambio de medio: P03-04 | Transferencia pendiente→efectivo→confirmación produce un abono y un movimiento |
| H10 | Egresos y aplicaciones: P03-05 | Proveedor, existencia, saldo, elegibilidad e importe verificados bajo bloqueo |
| H11 | Productos de factura: P04-02 | Referencia/relación/total inválido rechaza la factura completa con error localizado |
| H12 | Historia y borrados: P03-07, P04-04 | Factura pagada y relaciones históricas protegidas; anulación/reversión probadas |
| H13 | Ventas compartidas: P05-01 | Caso 300/3, participantes únicos, anuladas, gráfico y totales de empresa coherentes |
| H14 | Inventario de otra venta: P04-03 | Reserva ajena rechazada; asignación válida de stock libre autorizada |
| H15 | Concurrencia/idempotencia: P03-06, P04-03 | MySQL simultáneo sin pagos, números ni reservas duplicados; reintento estable |
| H16 | Entornos: P01-02 | DEBUG no cambia destino; staging/pruebas aislados; precedencia de variables comprobada |
| H17 | Impresión QR: P02-07, P08-09 | Datos no ejecutan HTML/JS; impresión y política de contenido compatibles |
| H18 | Plataforma/dependencias: P07-01, P07-02 | Runtimes soportados, locks reproducibles y auditoría vigente con excepciones justificadas |
| H19 | Multiplicador general: P05-03, P05-04 | Exactamente uno; reemplazo atómico; configuración inválida visible; cargos legítimos preservados |
| H20 | GET de permisos: P02-03 | Consulta sin escrituras ni cambio de acceso; roles migrados según matriz |
| H21 | Privilegios: P02-04 | Política explícita, autoelevación impedida, último administrador protegido y cambios auditados |
| H22 | Despliegue/recuperación: P01-05, P07-04, P07-05 | Fallos remotos propagados, salud exigida, release y restauración ensayadas |
| H23 | Pruebas/lint: P00-03, P00-04, P00-05, P07-03 | Descubrimiento completo, JSX analizado y regresiones críticas obligatorias en CI |
| H24 | Costo integral: P05-02, P06-02 | Caso 100 + 3 × 20 = 160; Decimal, grupos y telas heredadas sin doble conteo |
| H25 | Selectores: P08-02 | Más de 100 registros accesibles por búsqueda/paginación; orden estable |
| H26 | Rendimiento: P08-01, P08-02, P08-03, P08-04 | Carga acotada, detalles bajo demanda y presupuesto medido de consultas/latencia |
| H27 | Detalles de órdenes: P04-02 | Lista vacía, cero y proveedor incorrecto rechazados en todas las rutas de escritura |
| H28 | Sesiones: P02-05, P02-06 | Revocación/MFA según política, contador compartido, timeout y recuperación sin loader infinito |
| H29 | Modularidad: P03-01, P08-04, P08-05 | Reglas en servicios probados; contratos/hooks y estado de servidor fuera de contexto |
| H30 | Imágenes/correos: P07-06 | Límites y formato real; envío persistente con reintentos/estado honesto |
| H31 | Tiempo de negocio: P05-05 | Bordes nocturnos, día 5/6 y cambio de año coherentes en módulos |
| H32 | Trazabilidad: P03-07, P06-01, P10-05 | Relaciones y autores, períodos controlados, conciliaciones y auditoría de acciones sensibles |
| H33 | Identificadores/datos: P04-05, P06-02, P06-03 | Generación sin agotamiento aleatorio, QR antiguos válidos, sedes y fuentes consolidadas |
| H34 | Documentación/operación: P00-01, P07-07 | Guía consistente, decisiones, métricas/alertas accionables y configuración real verificada |

### Experiencia de uso

Los identificadores U01–U10 corresponden, en orden, a las diez propuestas de experiencia de informe.md.

| ID | Mejora | Tareas | Evidencia mínima |
|---|---|---|---|
| U01 | Expediente por venta | P09-05, P11-04 | Documentos, pendientes y responsable consultables desde la venta |
| U02 | Borrador y recuperación | P08-06, P09-02 | Fallo de red/sesión no pierde formulario ni filtra borradores |
| U03 | Errores junto al dato | P04-02, P08-06 | Error de fila/campo conserva valores y distingue su causa |
| U04 | Acciones según estado | P08-08 | Acciones correctas, explicación de bloqueo y mismo control por API |
| U05 | Tablas operativas | P08-02, P08-03, P08-08 | URL, fechas, columnas, total filtrado y exportación coherentes |
| U06 | Modal común accesible | P08-07 | Foco inicial/confinado/devuelto, teclado, nombre y overlay correctos |
| U07 | Accesibilidad práctica | P08-07, P14-03 | Recorridos de caja/ventas/bodega con teclado y contraste verificado |
| U08 | Impresión coherente | P02-07, P08-09 | Varias páginas, formato estable, datos seguros y “Pagado” preservado |
| U09 | Bodega/transporte móvil | P11-05 | Escaneo y entrega en dispositivo; reconexión sin duplicados si se habilita cola |
| U10 | Notificaciones y cargas | P02-06, P08-07 | Avisos accesibles, detalle recuperable y ninguna carga local congela toda la aplicación |

### Evolución funcional

Los identificadores F01–F16 corresponden, en orden, a las dieciséis filas de evolución funcional del informe.

| ID | Mejora | Tareas | Evidencia mínima |
|---|---|---|---|
| F01 | Cotizaciones persistentes | P09-01, P09-02, P09-04 | Número, cliente, asesor, vigencia, descuento/versión y conversión persistentes |
| F02 | Venta con líneas | P09-03, P09-06 | Cantidad, variante/tela/opciones, precio y compromiso; historia compatible |
| F03 | Flujo completo de mercancía | P09-05, P11-04 | Recorrido de punta a punta con vínculos y responsables verificables |
| F04 | Recepción parcial | P11-01 | Pedido↔recibido↔facturado, faltantes/devoluciones y ningún stock duplicado |
| F05 | Cartera por cliente, sin vencimiento (D10a) | P10-01, P10-05 | Saldos/promesas/anticipos y aplicaciones que explican el saldo; no clasificación por mora |
| F06 | Cuentas por pagar | P10-02, P10-05 | Vencimientos, parciales, descuentos y transferencias sin perder historia |
| F07 | Conciliación bancaria | P10-03 | Referencia/soporte/fecha, sugerencias revisables y deduplicación |
| F08 | Turnos de la única caja (D10b) | P03-02, P10-04 | Apertura/responsable/conteo/diferencia/cierre sin sobrescribir saldo ni repartirlo por sedes |
| F09 | Inventario reservable | P04-03, P11-02 | Disponibilidad separada de condición, movimientos y conteos trazables |
| F10 | Entregas parciales | P11-03, P11-05 | Pendientes por línea, evidencia, novedades/devolución y reserva única |
| F11 | Precio/margen versionados | P05-04, P09-01, P12-01 | Precio aceptado inmutable; impacto y margen con costo integral |
| F12 | Comisiones explicables | P12-02 | Regla versionada, reparto, período y ajustes rastreables |
| F13 | Atención posventa | P12-03 | PQRS/garantía/reparación/visita con unidad, responsable y resolución |
| F14 | Tablero de excepciones | P12-04 | Condiciones y acciones útiles para atrasos, telas, pagos, entregas y datos |
| F15 | Integración contable/fiscal | P13-01, P13-02 | D06a: SIIGO confirmado, sin intercambio solicitado por ahora; adaptador fuera de alcance y no implementado. Si se reabre: contrato y prueba en sandbox/exportación conciliada |
| F16 | Calidad/exportación de datos | P13-03, P13-04 | Duplicados revisables, normalización, exportación por permiso y conservación definida |

## 7. Anexo A — Convertir las 26 observaciones en regresiones

Conservar los nombres de observación para poder comparar con resultados.json. No conservar el resultado defectuoso como aserción esperada. Tres observaciones documentaban controles correctos; la prueba intercalada de reserva debe ampliarse a simultaneidad real en MySQL.

| Observación original | Resultado que debe comprobar la regresión | Tarea |
|---|---|---|
| negative_cash_income | Rechazo sin movimiento ni cambio de saldo | P03-03 |
| read_only_cash_permission_can_set_balance | Usuario lector no puede crear cierre ni fijar saldo | P03-02 |
| expense_error_retains_writes | Egreso fallido no conserva comprobante, aplicación ni factura pagada | P03-01 |
| expense_accepts_other_supplier_and_amount | Rechazo de proveedor/importe incompatibles sin cambios | P03-05 |
| edit_permission_bypasses_payment_approval | Edición sin aprobación no confirma estado ni aplica efectos | P02-02 |
| edit_foreign_sale_and_customer_with_state_permission | Consulta y escritura ajenas rechazadas; cliente sin modificar | P02-01 |
| alternate_order_endpoint_bypasses_ownership | Ruta normal y completa respetan el mismo alcance | P02-01 |
| inventory_cost_visible_without_cost_permission | Respuesta no contiene costos para usuario sin permiso | P02-02 |
| remision_put_bypasses_patch_permission | Conservar PUT no permitido; el nombre original no prueba un bypass | P04-04 |
| remision_read_permission_can_delete | Conservar DELETE no permitido e inventario intacto | P04-04 |
| invoice_edit_deletes_stock_identity_and_history | Identidad, remisión e historial permanecen | P04-01 |
| invoice_accepts_invalid_product_and_total | Entrada inválida rechazada completamente con error de fila | P04-02 |
| cost_omits_new_fabric_rows | Costo integral 160 bajo regla acordada, sin doble conteo | P05-02 |
| shared_sales_three_people | Cada participante recibe 100 de la venta de 300 | P05-01 |
| cancelled_sale_in_dashboard | La anulada no altera el indicador aplicable | P05-01 |
| transfer_changed_to_cash_missing_cash_movement | Confirmación aplica exactamente un ingreso y un abono | P03-04 |
| read_price_permission_allows_bulk_mutation | Lector no modifica multiplicador | P02-02 |
| remision_reserves_inventory_of_foreign_sale | Ítem ajeno rechazado y no reservado | P04-03 |
| interleaved_remision_validation_allows_double_reservation | Una reserva activa; repetir con transacciones MySQL independientes | P04-03 |
| paid_invoice_delete_bypasses_edit_safeguard | Documento pagado no desaparece ni pierde relaciones | P04-04 |
| viewing_role_configuration_removes_aux_default_permissions | GET no crea configuración ni cambia autorización efectiva | P02-03 |
| supplier_choices_silently_truncated | UI encuentra los 103 proveedores con paginación/búsqueda | P08-02 |
| empty_order_is_correctly_rejected | Conservar rechazo de orden vacía | P04-02 |
| zero_quantity_and_wrong_supplier_reference_accepted | Rechazar cero y referencia de proveedor ajeno, también por separado | P04-02 |
| catalog_general_multiplier_can_be_unset | No queda catálogo sin general ni respaldo silencioso a 1 | P05-03 |
| user_manager_can_self_promote_to_admin | Política acordada impide autoelevación y protege administración | P02-04 |

Añadir casos que no estaban en esas 26 observaciones: fallo en mitad de cada edición financiera, doble confirmación real, numeración simultánea, caja inicialmente vacía, datos de impresión maliciosos como texto, sesión/revocación, imágenes grandes, correo fallido, límites temporales, migraciones interrumpidas y recuperación de datos.

## 8. Comprobaciones técnicas y evidencia por entrega

Estos comandos son referencias de la base auditada y deben verificarse contra el entorno actual. **No ejecutan despliegues.** Las pruebas deben utilizar siempre el perfil aislado, nunca inferir una base desde DEBUG ni reutilizar las credenciales remotas de .env.

En ordenesPedidoSWBackend, el intérprete local disponible durante la auditoría era testenv/bin/python. Tras actualizar Python, sustituirlo por el intérprete del entorno virtual nuevo:

~~~sh
testenv/bin/python manage.py test --settings=lottusPedidos.settings_test --noinput
testenv/bin/python manage.py makemigrations --check --dry-run --settings=lottusPedidos.settings_test
testenv/bin/python manage.py check --settings=lottusPedidos.settings_test
~~~

Después de editar archivos Python, ejecutar py_compile con los **archivos realmente modificados**; por ejemplo, únicamente si se cambiaron esos archivos:

~~~sh
testenv/bin/python -m py_compile ordenes/views.py ordenes/serializers.py
~~~

El perfil settings_test auditado usa SQLite en memoria. Definir en P00 el comando separado de integración MySQL y documentarlo aquí al crearlo; no presentar la ejecución SQLite como validación de bloqueos de MySQL. Las carreras deben sincronizar dos o más transacciones/conexiones independientes y verificar tanto el estado final como las respuestas; evitar pruebas basadas solo en pausas arbitrarias.

En ordenesPedidoSW:

~~~sh
npm run build
~~~

Los scripts siguientes **no existían en package.json al auditar**; agregarlos/configurarlos en P00/P07 y documentar sus herramientas/opciones antes de exigirlos:

~~~sh
npm run lint
npm run test
npm run test:e2e
~~~

Para una comprobación local de documentación o un cambio reversible sin comportamiento, no crear tests que solo reflejen la implementación. Para dinero, permisos, inventario, migraciones y contratos, las regresiones son obligatorias. Escoger casos que verifiquen la regla y sus límites; no usar un porcentaje global de cobertura como sustituto.

### Evidencia que debe acompañar cada entrega

- Problema concreto y comportamiento posterior, con IDs H/U/F y tareas del plan.
- Archivos y migraciones afectados en cada repositorio; versión compatible de frontend/backend.
- Pruebas ejecutadas y resultado real, entorno/motor, casos manuales y comprobaciones pendientes.
- Efectos en datos, contrato, permisos, rendimiento y operación; estrategia de activación/recuperación.
- Decisiones nuevas, excepciones e instrucciones suficientes para que otro agente continúe.

Los logs de prueba no deben contener tokens, contraseñas, datos personales ni copias completas de documentos reales. Un error de negocio antes del commit debe conservar el estado anterior. Un timeout después del commit tiene resultado inicialmente incierto: recuperarlo consultando/reintentando con idempotencia, sin asumir que la operación falló ni volver a aplicarla.

## 9. Definición de completado

El agente solo puede declarar completado el alcance cuando:

1. La matriz H01–H34, U01–U10 y F01–F16 tiene estado y evidencia para cada elemento, incluidos cambios de alcance explícitamente acordados.
2. Cada operación financiera aceptada cuadra; cada rechazo conserva los datos; confirmación/reversión es única bajo repetición y concurrencia real.
3. Las rutas normales, alternativas, exportaciones e impresiones respetan permisos de objeto y campo.
4. Identidades, QR, relaciones y documentos históricos se conservan; migraciones y reparaciones están conciliadas.
5. Los cálculos de costo, precio, reparto, fechas, cartera, pagos y comisiones se explican desde reglas/documentos versionados.
6. Los flujos existentes y las reglas de PDF/caja/ventas compartidas/órdenes se mantienen, con experiencia comprobada por los roles afectados.
7. Pruebas, lint, build, migraciones e instalación reproducible funcionan; no quedan fallos silenciados ni análisis de dependencias presentados como hechos sin ejecutarse.
8. Las funciones nuevas tienen decisión de negocio, contrato, permisos, datos históricos tratados y recorrido de extremo a extremo verificado.
9. Despliegue, observabilidad, backup y restauración están documentados y ensayados; el estado real de publicación está claramente indicado.
10. Seguimiento, decisiones y operación permiten continuar sin depender de memoria de la conversación.

Si alguna condición material sigue pendiente, entregar el avance útil, explicar el impedimento concreto y mantener abiertos sus IDs. **El tamaño del cambio, el tiempo invertido o que el build pase no bastan para declarar el ERP mejorado por completo.**
