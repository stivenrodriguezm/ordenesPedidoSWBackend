# Chat lateral y acceso rápido por cuenta — 2026-10-09

Solicitud implementada en localhost:3000 y localhost:8000.

- El chat ocupa la altura completa y toca los bordes superior, derecho e inferior. Conserva `clamp(480px,48vw,760px)` en escritorio y el ancho móvil previo de la pantalla menos 16 px. Sigue superpuesto, sin velo ni bloqueo de la página. Se eliminaron también las reglas de la oficina que reintroducían margen superior.
- `ChatLateralProvider` comparte el panel entre la oficina y el resto de la plataforma. Navegar conserva el chat y sus borradores; cerrar devuelve el foco y permite reabrir. Se mantienen historial por agente, cambio de agente, Escape y ampliación.
- El botón discreto «IA» se muestra según `CustomUser.acceso_rapido_ia` y el permiso de uso de IA. La preferencia controla el acceso rápido, sin conceder permisos de consulta de datos. Los administradores no omiten esta preferencia.
- Gestión de usuarios muestra el estado por cuenta. El formulario permite activarlo/desactivarlo solo al rol administrador; la API rechaza el campo para gestores no administradores tanto en creación como edición. La edición propia recarga la sesión. Los cambios quedan auditados.

## Base de pruebas usada por el backend local

El backend local apunta a MySQL `u756180748_pruebasv3`. Se identificaron las cuentas existentes Stiven (ID 5) y Oscar (ID 6), ambas administradoras. Se aplicó únicamente `0069_customuser_acceso_rapido_ia`, tras verificar que el plan contenía solo esa migración y guardar el estado previo de las cuentas afectadas y el historial de migraciones en `.cache/acceso_rapido_ia_antes_20261009_085146.json` (0600). El campo nuevo queda apagado por defecto; se activó para los IDs 5 y 6 con auditoría. Para revertir esta preferencia basta desmarcarla en estas cuentas.

El merge 0061, que todavía no se ha aplicado, depende ahora de 0069 para conservar una sola hoja en el grafo. No se ejecutó 0057 ni el merge. No hubo despliegue de código.

## Validación

- Suite frontend existente más acceso lateral: 208 pruebas correctas en 39 archivos. Gestión de usuarios: 2 pruebas adicionales correctas (guardado propio con recarga y omisión para gestores no administradores).
- Backend: 16 pruebas correctas en `test_acceso_rapido_ia` y `test_permisos`, con SQLite aislado y sin servicios externos.
- ESLint de archivos modificados sin errores. Build correcto y `makemigrations --check --dry-run` sin cambios pendientes.
- Navegador real: botón en Recibos de caja, apertura sin cambiar ruta, navegación a oficina conservando el panel, historial existente, conversación nueva sin enviar preguntas, cierre e interruptor activado en Stiven. La tabla confirma también Oscar activado.
- Panel en escritorio: top/right/bottom 0 y ancho 705,59 px en viewport de 1470 px. Móvil 390 × 844: ancho 374 px, bordes 0 respecto al área disponible, entrada visible. Se restauró el viewport de escritorio.

Evidencias: `evidencias/chat-ia-lateral-bordes.jpg`, `evidencias/chat-ia-lateral-movil.jpg`, `evidencias/chat-ia-configuracion-usuario.jpg`.
