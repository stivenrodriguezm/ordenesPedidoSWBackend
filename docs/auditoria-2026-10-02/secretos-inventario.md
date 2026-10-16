# Inventario de exposición de credenciales (P01-01)

Fecha: 2026-10-02. **Este documento no contiene valores**: solo servicio, entorno, ubicación y relación de reutilización.
Responsable de rotar: propietario de las cuentas de Hostinger/VPS (pendiente de nombrar en [decisiones.md](decisiones.md)).

| # | Servicio / credencial | Entorno | Ubicación | Versionado | Reutilización | Estado |
|---|---|---|---|---|---|---|
| S1 | Contraseña MySQL de la base de producción | producción | `ordenesPedidoSWBackend/deployment_guide.md` (línea del `mysqldump`) | **Sí**: presente en 12 commits del historial del backend (remoto GitHub) | El mismo valor se usa como contraseña SSH y `sudo` del VPS (según DEPLOY_VPS.md) | Saneado en el árbol de trabajo (rama `auditoria-2026-10-02`); **sigue en el historial**; **no rotada** |
| S2 | Usuario/contraseña SSH y `sudo` del VPS | producción | `deploy_backend_vps.sh` y `DEPLOY_VPS.md` (raíz, fuera de git) | No (raíz sin git) | Igual a S1 | **Sin sanear** (raíz fuera del alcance de edición) · reemplazo preparado: `scripts/deploy/deploy_backend.sh` con llaves SSH |
| S3 | Contraseñas de bases (producción y pruebas) y root | producción / pruebas | `ENVIRONMENT_CONFIG.md`, `INSTRUCCIONES_PROYECTO.md` (raíz) | No | Indica relación con S1 | **Sin sanear** (raíz) |
| S4 | `.env` local del backend: DB_*, SIRV_*, CLOUDINARY_*, EMAIL_* | desarrollo (apunta a MySQL remoto) | `ordenesPedidoSWBackend/.env` | No (`.gitignore`) | DB_PASSWORD: el informe lo identifica igual a S1 | Local; rotar junto con S1 y redistribuir |
| S5 | `.env`, `.env.development`, `.env.production` del frontend | todos | `ordenesPedidoSW/` | Sí | Solo `VITE_API_BASE_URL` (URL pública, no es secreto) | Sin acción |
| S6 | `GEMINI_API_KEY` (Chat: asesor gerencial con IA, 2026-10-08) | desarrollo (y VPS al desplegar) | `ordenesPedidoSWBackend/.env` (permisos 600). Nunca en el frontend ni en commits | No (`.gitignore`) | Ninguna | Entregada por el usuario en el chat de desarrollo (queda en ese historial): **conviene restringirla en Google AI Studio y rotarla antes de producción**. Para el VPS se agrega a su `.env` a mano |
| S6 | Carpeta `venv/` completa versionada en el frontend (8146 archivos) | — | `ordenesPedidoSW/venv` | Sí | No se hallaron credenciales; es higiene del repositorio | Pendiente: retirar del índice en una entrega coordinada |

Incidencia de esta ejecución: al escanear, un filtro de enmascarado falló y el valor de S2 apareció una vez en la salida local de la herramienta de la sesión. No se escribió en ningún archivo ni commit. Refuerza la urgencia de rotar.

## Plan de rotación coordinada (P01-03) — requiere autorización explícita

1. Crear credenciales nuevas **distintas** por servicio: MySQL producción (usuario de aplicación con permisos mínimos), MySQL pruebas/staging (sin acceso a producción), usuario de despliegue del VPS con llave SSH y `sudo` limitado (`systemctl restart|is-active gunicorn`), desactivar acceso SSH por contraseña.
2. Actualizar consumidores: `.env` del VPS, `.env` local de desarrollo, `~/.my.cnf` del usuario de despliegue (respaldos).
3. Verificar: `manage.py check`, `/api/health/` en 200, login real.
4. Revocar las credenciales antiguas (MySQL, SSH, sudo). Confirmar que ya no funcionan.
5. Después de rotar: decidir con el equipo la reescritura del historial del backend (requiere coordinación por ser historia compartida) o registrar el hallazgo como permanente en `.gitleaksignore` con su justificación. La CI `secretos` fallará hasta entonces, a propósito.
6. Sanear la raíz (S2, S3): pedir ampliación de alcance o hacerlo el propietario. Sustituir `deploy_backend_vps.sh` por `scripts/deploy/deploy_backend.sh`.

**No se reactivan credenciales expuestas para revertir.**
