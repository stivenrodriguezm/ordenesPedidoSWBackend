# Error 429 al cargar la sesión en localhost — 2026-10-09

El contador compartido `user` había alcanzado exactamente 10.000 solicitudes en las últimas 24 horas. Incluía los sondeos de presencia, interacciones, actividad y conversaciones de la oficina. Al recargar, `GET /api/user/` utilizaba el mismo contador y rechazaba una sesión válida.

`ApiUserRateThrottle` ahora separa las solicitudes autenticadas por finalidad. Las consultas automáticas tienen una lista explícita de rutas; las demás consultas y las escrituras siguen utilizando el cupo operativo. Academia, login y PQRS conservan sus límites específicos.

| Finalidad | Límite por usuario | Contador |
| --- | --- | --- |
| Consultar la sesión, GET/HEAD `/api/user/` | 60/minuto | `session` |
| Consultas de actividad de oficina y chat | 180/minuto | `office_live` |
| Latido de presencia, POST `/api/oficina/presencia/` | 10/minuto | `office_presence` |
| Resto de solicitudes autenticadas | 10.000/día | `api_user` |

La nueva clave operativa evita reutilizar el contador anterior que mezclaba actividades. El contador viejo se conserva hasta su vencimiento; no se borró la caché ni se modificaron datos de negocio. Autenticación y permisos siguen siendo obligatorios.

Si la sesión recibe un 429 real, el frontend informa el tiempo indicado por `Retry-After`, conserva los tokens y permite reintentar.

## Verificación

- 7 regresiones del nuevo throttle: contador anterior agotado, cupos independientes, aislamiento entre usuarios, expiración del límite, escrituras, autenticación y latidos de presencia.
- 25 regresiones existentes de Academia y permisos; 8 pruebas frontend de sesión, rutas privadas y renovación de tokens. Todas pasaron.
- ESLint sin errores; compilación Vite correcta.
- En Chrome se recuperó la sesión existente y volvió a cargar la oficina. La caché real mostró el contador antiguo aún en 10.000, separado de los nuevos contadores de sesión, operaciones y actividad.
- Evidencia: `evidencias/oficina-recuperada-429.jpg`.

No se ejecutaron migraciones ni despliegues.
