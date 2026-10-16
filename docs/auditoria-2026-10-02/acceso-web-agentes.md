# Acceso a la página web por agente

En «Gestionar agentes → Datos que puede consultar» aparece «Página web». El administrador puede activarla y revocarla individualmente; los perfiles existentes conservan sus áreas. Se guarda en el JSON `areas`, sin migración. La IA general conserva su acceso a todas las herramientas.

El permiso habilita tres herramientas de consulta, con validación del área en el servidor:

- `consultar_pagina_web`: páginas, textos, enlaces, metadatos SEO, colores, tipografías, adaptación a pantallas, archivos, catálogo activo y asesores publicados.
- `leer_codigo_pagina_web`: código paginado por líneas del sitio público (`webLottus`), la landing, el módulo de Gestión web del ERP y la API `paginaweb` (modelos, serializers, vistas, rutas y procesamiento de imágenes).
- `ver_imagen_pagina_web`: imágenes reales de los archivos públicos y fotografías de productos publicados, procesadas para análisis multimodal. Máximo tres imágenes por respuesta.

Los archivos se seleccionan desde un índice cerrado. No se aceptan rutas libres, enlaces simbólicos, archivos de entorno, claves, registros privados, PQRS ni el resto del ERP. Las fotografías remotas solo proceden de URLs publicadas en el catálogo y CDN admitido (Sirv/Cloudinary); no se siguen redirecciones y hay límites de bytes y píxeles. No se escribe código ni se publica contenido.

El análisis visual se basa en imágenes y estilos reales, sin afirmar que son capturas de páginas renderizadas. El código corresponde al checkout local y puede diferir del sitio desplegado. Las raíces pueden configurarse con `ASISTENTE_WEB_ROOT`, `ASISTENTE_LANDING_ROOT`, `ASISTENTE_GESTION_WEB_ROOT` y `ASISTENTE_BACKEND_WEB_ROOT`; si no hay checkout, el resultado informa que faltan los archivos y sigue ofreciendo el catálogo público.

Las imágenes no se convierten en texto base64 ni se guardan en los mensajes: se envían como partes multimodales. Gemini 3 recibe `functionResponse.parts`, según la [documentación oficial](https://ai.google.dev/gemini-api/docs/generate-content/function-calling?hl=en); los modelos anteriores reciben partes de imagen junto a la respuesta de la herramienta.

Verificación: 27 pruebas del backend (web, perfiles, asistente y vida de oficina), 14 del frontend (perfiles y recorridos), ESLint y compilación. Incluye activación/revocación, catálogo sin precios internos ni borradores, rutas y enlaces maliciosos, código del módulo de gestión/API y transporte de imagen sin guardarla como texto.

En Chrome, con la IA general de Stiven, se ejecutó una consulta real con `gemini-3.7-flash`: leyó el título «LOTTUS · Diseño de autor para el hogar · Bogotá», identificó paleta y fuentes del CSS y describió la fotografía `public/img/seed/hero.jpg` tras recibir la imagen. El registro mostró las tres herramientas. Se verificó la casilla en el Director de marketing sin activar automáticamente su permiso.

Evidencias: `evidencias/permiso-pagina-web.jpg` y `evidencias/consulta-pagina-web.jpg`.
