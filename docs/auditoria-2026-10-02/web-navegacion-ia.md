# P16 — Web, navegación e IA

Entrega local del 8 de octubre de 2026. Fuente: seis puntos del prompt adjunto del usuario, continuando cambios del agente anterior. No publicada en producción. Estado principal: [planMejora.md](planMejora.md).

## Cómo revisar la entrega

1. Abrir el ERP en `http://localhost:3000` con su API en `http://localhost:8000`. Mantener la conexión existente a `u756180748_pruebasv3`; no sustituirla por fixtures ni copiar credenciales a comandos o documentos.
2. En Productos → Gestión web, editar un producto existente. Hay cuatro campos extensibles: descripción corta, descripción larga, características y materiales. La barra inserta formato de texto y la vista previa lo interpreta antes de guardar. Se admite negrilla, cursiva, listas, subtítulos y separadores; no HTML arbitrario.
3. Abrir el catálogo local en `http://localhost:4000`. Sala Finlandia ya tiene las cuatro secciones con datos existentes: se verificaron descripción, dimensiones con etiqueta en negrilla y materiales. Los demás productos conservan sus textos existentes; completar los vacíos requiere contenido editorial real del negocio. No hay precios en tarjetas, detalle, variantes, formulario ni respuesta de la API.
4. En Administrar lista, expandir Alaska / Sofá 3p. Revisar los paneles de cargos, multiplicador y precios por grupo. El guardado al salir del campo y los cálculos mantienen su comportamiento. Solo esa opción del menú debe aparecer seleccionada.
5. En IA Lottus, solicitar un gráfico con fechas concretas. Ejemplos: «Grafica las ventas por sede entre el 1 y el 30 de septiembre de 2026 y explica oportunidades de crecimiento» o «Compara los cobros confirmados de dos períodos equivalentes e identifica riesgos de caja». Los gráficos incluyen fuente, filtros y notas; se pueden consultar como tabla o descargar en PNG.

El asistente requiere la configuración Gemini ya existente y el permiso `USAR_ASISTENTE_IA`. Las conversaciones siguen siendo privadas por usuario. Esta entrega verificó el proveedor con respuestas simuladas, no una nueva respuesta real de Gemini ni el consumo facturado. Las consultas de datos sí se ejecutaron en MySQL real de pruebas, de solo lectura. Los errores históricos de conversación no se borraron ni se presentaron como respuestas exitosas.

## Implementación

| Área | Archivos principales | Contrato |
|---|---|---|
| Contenido web | `paginaweb/models.py`, `serializers.py`, `migrations/0005_caracteristicas_con_formato.py`; frontend `EditorTextoFormato`, `PaginawebAdminPage`; web `main.js`, `producto.js`, `sora.js` | Nueva sección `characteristics`; backfill conserva dimensiones/características anteriores. Precios históricos permanecen en base, pero no se publican ni se editan por API. Formato con escape HTML. |
| Navegación | `Sidebar.jsx`, `App.jsx`, `Header.jsx`, `UsuariosPage.jsx` | General/Finanzas/Bases de datos/Productos/IA; sin Suministros como grupo, sin Bancos; ruta exacta para Consultar precios. |
| Referencias | `pages/listaprecios/ListaPreciosAdminPage.jsx` y CSS | Mejora visual y accesibilidad del panel expandido sin sustituir las mutaciones comerciales. |
| Analítica | `ordenes/asistente/analitica.py`, `herramientas.py` | ORM con dominios, dimensiones, métricas y filtros permitidos; fechas incluidas; hasta 50 grupos; totales completos separados del top y advertencia si se trunca. |
| Gráficos | `ordenes/asistente/graficos.py`, `gemini.py`, `views.py`; frontend `components/chat/GraficoDatos` | Solo datos consultados en el mismo turno; se almacenan con la respuesta. Barras, líneas y dona validada, tabla accesible y PNG. |
| Estrategia y consumo | `contexto_negocio.md`, `gemini.py` | Distingue hechos, hipótesis y escenarios; comparte ventas por Total/N; no convierte antigüedad en mora. Reutiliza consultas, limita rondas a 8, llamadas a 16, gráficos a 3, historial a 24.000 caracteres y cada resultado a 16.000 caracteres. No se afirma un ahorro porcentual medido. |

La herramienta `consulta_datos` trabaja con ventas no anuladas, productos confirmados, pedidos no anulados, pagos confirmados e inventario. El precio de lista es cantidad × precio unitario y no representa ingreso negociado. Inventario y saldos describen su estado actual dentro del conjunto filtrado; no reconstruyen cortes históricos. El inventario por fechas corresponde a fecha de ingreso. Agrupación mensual significa mes calendario; las herramientas comerciales existentes conservan su propio período y lo explican.

No se ofrece SQL libre: el modelo elige parámetros de consulta, el servidor valida y agrega los datos. `graficar_consulta` recibe el identificador de una consulta y una métrica, y obtiene sus valores en el servidor. No acepta cifras inventadas por el modelo como fuente del gráfico. Una dona requiere conjunto completo, hasta diez categorías y valores no negativos.

## Migraciones y respaldo

**Aplicada:** `paginaweb.0005_caracteristicas_con_formato` en pruebasv3. La API pública devolvió 200, 12 productos y ningún campo de precio publicado. Uno de esos productos ya tiene las cuatro secciones no vacías. No se añadieron registros de demostración.

**Pendiente y bloqueada:** `ordenes.0057_eliminar_bancos`. Retira `VER_BANCOS` y `CONCILIAR_BANCOS` de los permisos de rol y elimina estas tablas en orden de dependencia:

1. `ordenes_conciliacionbancaria`
2. `ordenes_movimientobancario`
3. `ordenes_extractobancario`
4. `ordenes_cuentabancaria`

No elimina recibos, pagos de recibos, egresos ni medios de pago; elimina los registros de conciliación que los vinculaban al módulo Bancos. El código del módulo y su API ya se retiraron. Las migraciones antiguas permanecen como historia del esquema.

La revisión automática rechazó la aplicación conjunta de migraciones porque no consideró que el transcript autorizara explícitamente borrar el módulo y su alcance. Se continuó únicamente con la migración web, aprobada por separado. **No ejecutar 0057 hasta recibir confirmación explícita para estas tablas y permisos en pruebasv3.** No inferirla de un «continúa» genérico ni intervenir producción.

Respaldo completo disponible en `respaldos_locales/pruebasv3_antes_web_bancos_20261008_165357.sql.gz`, relativo a la raíz del workspace. Se verificaron el dump completo, su descompresión y permisos 0600. No se ensayó una restauración en esta entrega. La conexión inicial expiró durante el respaldo; la migración web se aplicó después con conexión nueva. No hubo una aplicación parcial de esa migración.

Después de obtener la confirmación:

1. Verificar de nuevo destino MySQL y nombre exacto `u756180748_pruebasv3`. Revisar `migrate ordenes 0057_eliminar_bancos --plan`; si incluye migraciones adicionales, inspeccionarlas antes de proceder.
2. Comprobar vigencia del respaldo; si hubo cambios desde su creación, generar otro respaldo consistente antes de borrar tablas.
3. Aplicar únicamente `ordenes 0057_eliminar_bancos` con las credenciales existentes del entorno, sin exponerlas.
4. Verificar ausencia de las cuatro tablas y de los dos códigos en permisos de rol. Comparar los conteos de recibos, sus pagos y egresos con el corte previo. Comprobar que la ruta `/api/bancos/cuentas/` devuelve 404 y que Caja/Recibos/Egresos mantienen su carga normal.
5. Actualizar P16-02, seguimiento y evidencia. La reversión de la migración recrea estructura vacía; **no recupera registros eliminados ni permisos**. Para recuperarlos hace falta restaurar selectivamente desde respaldo verificado, primero en una base aislada; no sobrescribir trabajo nuevo de la base activa.

La publicación sigue pendiente. Debe coordinar backend, ERP y catálogo: la migración web debe preceder al código que lee `characteristics`, y los recursos públicos deben publicarse junto con el nuevo contrato sin precios. Usar la guía de despliegue existente con destino verificado y autorización de publicación. No ejecutar un `migrate` indiscriminado mientras 0057 siga bloqueada.

## Evidencia técnica

Ejecutado con dependencias locales existentes, sin incorporar nuevas librerías:

```sh
# Backend: base SQLite desechable, sin cargar el .env de operación
DJANGO_ENV_FILE='' testenv/bin/python manage.py test --settings=lottusPedidos.settings_test --noinput
# Resultado: 309 descubiertas, 300 correctas y 9 omitidas por requerir MySQL.

# Cierre dirigido, después de añadir la regresión de tamaño de resultados
DJANGO_ENV_FILE='' testenv/bin/python manage.py test ordenes.tests.test_analitica_asistente ordenes.tests.test_asistente paginaweb.tests --settings=lottusPedidos.settings_test --noinput
# Resultado: 24 correctas. Incluye una nueva prueba posterior al corte completo.

# Frontend
npm test
# Resultado: 135 correctas en 28 suites.
npm run lint
# Resultado: 0 errores, 20 advertencias existentes.
npx vite build --outDir .build-check --emptyOutDir
# Resultado: correcto; repetido tras los últimos ajustes de presentación.
```

También se ejecutaron 11 pruebas dirigidas de ChatPage, Sidebar, GraficoDatos y EditorTextoFormato tras los ajustes finales, ESLint de componentes afectados, `py_compile`, comprobación de migraciones y sintaxis de scripts públicos. Los avisos React Router son de compatibilidad futura; el mock del gráfico en pruebas emite un aviso de ref que no corresponde al componente Chart.js real.

Las verificaciones cubren filtros/rangos, totales fuera del top, decimales, cantidad por precio, exclusión de cobros pendientes/anulados, gráficos con origen válido, recuperación de errores de herramienta, caché, persistencia de gráficos, límite de tamaño, ruta Bancos retirada, cuatro secciones, backfill y escape HTML. Lectura real de pruebas: cinco dominios, fechas por día/semana/mes, total de ventas contrastado con una agregación independiente; resultado por sede de 1.058 caracteres. Ninguna de esas lecturas se usó como fixture ni se envió a Gemini durante esta validación.

Registros temporales: `/private/tmp/lottus-web-ia-backend-completo.log`, `lottus-web-ia-cierre-backend.log`, `lottus-web-ia-frontend-completo.log`, `lottus-web-ia-lint.log` y `lottus-web-ia-build-cierre.log`. Esta guía conserva los resultados porque los temporales pueden eliminarse.
