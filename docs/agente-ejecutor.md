# Agente ejecutor en localhost

Verificado el 9 de octubre de 2026. Frontend en 3000 y backend en 8000.

IA Lottus puede encargar una operación al perfil Agente mediante `ejecutar_con_agente`.
Hablar directamente con Agente también crea una ejecución privada y persistente. La
oficina tiene un único Agente, perfil 5, ubicado en Oficina. La migración 0072 transfirió
las conversaciones, documentos, aprendizajes, automatizaciones, cursos y referencias
de oficina del perfil duplicado antes de retirarlo.

## Operaciones disponibles

El ejecutor consulta los campos de los formularios y los registros con los permisos
del usuario que dio la orden. Usa las mismas vistas, validaciones, revisiones,
consecutivos y servicios que utiliza la plataforma. No ejecuta código generado ni
SQL del modelo y no admite rutas arbitrarias.

- Crear y editar ventas; guardar sus productos vendidos; agregar observaciones.
- Registrar entre 1 y 20 ventas completas por lote, con alta y productos juntos.
- Crear y editar pedidos a fabricantes y de telas.
- Crear referencias, proveedores y proveedores de telas.
- Actualizar inventario; crear y editar cotizaciones; pedir productos de una venta.
- Consultar clientes, ventas, vendedores, catálogo, productos, referencias, pedidos,
  proveedores, inventario y cotizaciones.

Los permisos por área de Agente y los permisos operativos del usuario se comprueban
en cada llamada. No puede gestionar usuarios, permisos ni credenciales, eliminar
registros o hacer transferencias. Una operación no disponible no debe anunciarse
como completada. Si faltan datos comerciales, pide únicamente los necesarios; no
inventa clientes, precios, asesores o productos. Datos ficticios requieren una petición
expresa de prueba.

Las tareas humanas requieren una orden expresa del usuario que nombre al destinatario.
La comprobación se hace en el servidor sobre el mensaje humano, además de las
instrucciones del modelo. Las tareas 8 y 9 que habían sido asignadas a Manuel para las
15 ventas quedaron canceladas mediante la API de oficina; su historial se conserva.

## Avance, resultados y reintentos

`TrabajoAgenteIA` conserva la solicitud, su propietario, estados, pasos y resultado.
El motor `ejecutar_automatizaciones_ia --continuo --intervalo 10` atiende la cola.
Desde la corrección del 10 de octubre de 2026, `manage.py runserver` también inicia
y supervisa el motor local, con la misma configuración y base de datos del servidor.
El proceso padre lo mantiene activo durante las recargas del servidor. El bloqueo
del motor impide duplicarlo si ya hay uno externo; `runserver --sin-motor-ia` permite
dejarlo bajo supervisión externa. En producción se conserva el servicio independiente
de `deploy/lottus-automatizaciones-ia.service.example`.
El motor cierra las conexiones de su coordinador antes de esperar entre ciclos,
para no reutilizar sockets MySQL ociosos que el servidor remoto haya cerrado.
La tarjeta distingue solicitudes en cola de ejecuciones iniciadas y muestra cuando
el último latido del motor está vencido, sin anunciar trabajo que todavía no comenzó.
La oficina muestra los recorridos, el trabajo y la entrega con eventos reales. El
contenido de una ejecución y sus registros son privados de su propietario.

El chat muestra una tarjeta de ejecución. El botón **Ejecuciones de Agente** permite
consultar el historial y el detalle; las ventas guardadas incluyen identificadores y
enlaces al módulo operativo. El sondeo se detiene al finalizar. Un fallo temporal de
red conserva el último resultado disponible.

Cada escritura tiene una clave estable y una huella de sus datos. La operación y su
registro de paso se guardan en una misma transacción. Repetir un paso idéntico devuelve
su resultado; cambiar sus datos con la misma clave se rechaza. Un lote de ventas se
revierte completo si cualquier producto es inválido. El cambio de modelo conserva la
memoria de llamadas y sus resultados. Un fallo posterior a un paso guardado mantiene
ese paso y muestra una ejecución que requiere revisión.

**Continuar con Agente** aporta datos a la misma ejecución y conserva sus pasos.
Una ejecución interrumpida no se repite automáticamente. Preguntar **«¿y el resultado?»**
consulta la ejecución existente, también al hablar directamente con Agente.

## Validación

Corrección del bloqueo del 10 de octubre: 52 pruebas de backend (motor, ejecutor y
automatizaciones) y 7 pruebas de la tarjeta de frontend; sintaxis Python y ESLint
correctos. Las regresiones comprueban el arranque único durante recargas, la opción
de motor externo, recuperación tras fallo, liberación del bloqueo y el aviso de motor
desconectado. Las operaciones de pruebas se ejecutan en SQLite aislado.
Las consultas internas usan un host permitido por la configuración del servidor:
la paginación deja de fallar por el `testserver` predeterminado de RequestFactory.
La regresión reproduce una lista de más de una página con `testserver` excluido de
`ALLOWED_HOSTS`.

- 50 pruebas de backend: delegación IA Lottus → Agente, escritura real de formularios,
  15 ventas con productos en SQLite aislado, reversión de lote inválido, permisos,
  privacidad, reintentos sin duplicados, cambio de modelo, datos faltantes, seguimiento,
  consolidación de perfiles, actividad de oficina y límites de solicitudes.
- 31 pruebas de frontend entre chat, perfiles, recorridos y tarjetas de ejecución.
  ESLint de los archivos afectados y compilación Vite correctos.
- Esquema Django: `makemigrations --check --dry-run` sin cambios pendientes.
- Prueba en vivo: IA Lottus creó la ejecución 1; Agente consultó `crear_venta` y
  `guardar_productos_venta` y entregó un resultado verificado. El seguimiento volvió
  a mostrar la ejecución 1. Solo existe una ejecución de esta prueba y una identidad
  Agente en Oficina.
- No se registraron las 15 ventas en la base usada por localhost, conforme a la
  aclaración del usuario. El número de ventas permaneció en 966 antes y después de
  la prueba de consulta. Las escrituras se comprobaron únicamente en pruebas aisladas.

Evidencia: [resultado completo](agente-ejecucion-verificada.png) y
[seguimiento en la oficina](agente-ejecutor-oficina.png).

En la base de pruebas se aplicó explícitamente solo
`migrate ordenes 0072_ejecutor_operativo_ia`. La rama pendiente de eliminación de
Bancos y su migración de unión no se aplicaron.
