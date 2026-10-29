# Reglas del proyecto LOTTUS para el Desarrollador

Plataforma ERP de LOTTUS (muebles, Bogotá). Dos repositorios en tu espacio de trabajo:
- `backend/`: Django + Django REST Framework. Apps `ordenes` (ventas, pedidos, caja, recibos, nómina, IA), `suministros` (inventario, facturas de proveedor, remisiones), `listaprecios`, `paginaweb`, `pagos`, `impresion`. Configuración en `lottusPedidos/`.
- `frontend/`: React + Vite (HashRouter). Páginas en `src/pages`, componentes en `src/components`, llamadas al API en `src/services`, utilidades en `src/utils`. Datos del servidor con React Query.

## Reglas del usuario (obligatorias)
- Textos de la interfaz en español claro y conciso.
- Dinero: pesos colombianos sin decimales, con `$` y puntos de miles (`$3.000.000`), en tablas, formularios y documentos. Los decimales del API (`"3000000.00"`) son tres millones. En campos de dinero rechaza centavos sin truncarlos y no conviertas vacío en cero; reutiliza `src/utils/capturaPrecios.js` (`leerPesos`, `mostrarPesos`) o `CampoPrecio.jsx`.
- Porcentajes con `%` fijo fuera del campo y sin flechas. Tela en metros y cuero en decímetros, separados.
- En celular las tablas se deslizan a lo ancho (no se convierten en tarjetas). No cambies la vista de computador al arreglar la de celular.
- Ventas guardadas son históricas: un cambio en la lista de precios nunca altera ventas ya guardadas.
- Módulos eliminados que NO se vuelven a crear (ni con otro nombre): Cuentas por pagar, Cartera, Conciliación, Turnos de caja, Posventa y Garantías, Excepciones, Conteos de inventario.
- Saldo de caja nunca negativo. Una orden de pedido siempre tiene al menos un producto.
- Modales con fondo opaco y centrados; los cargadores solo en el botón o tarjeta que carga.

## Cómo programar aquí
- Imita el estilo del código que lo rodea (nombres en español, densidad de comentarios, CSS con prefijo propio por vista, variables de tema `var(--...)`).
- Backend: vistas delgadas; lógica en funciones de servicio; `select_related`/`prefetch_related` para evitar N+1; permisos con `check_feature_permission('CODIGO')`.
- Base de datos: solo con cambios en los modelos de Django; la migración la genera el sistema después (no escribas archivos de migración a mano, no edites migraciones existentes, no uses SQL directo). Borrar modelos o campos con datos es riesgo alto.
- Cada cambio de comportamiento lleva su prueba: backend en `<app>/tests/` o `<app>/test_*.py` (clase base `ordenes.tests.utils.LottusTestCase`), frontend junto al componente (`*.test.jsx`, vitest + Testing Library).
- No agregues dependencias nuevas (requirements.txt, package.json) ni toques configuración del servidor, despliegue o credenciales.
- Haz el cambio más pequeño que cumpla el pedido; no reescribas archivos completos si basta con reemplazar un fragmento.
