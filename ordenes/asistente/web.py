"""Consulta acotada del sitio público: fuentes, contenido y fotografías reales.

No ejecuta código ni permite rutas arbitrarias. Las imágenes se transportan como
partes multimodales; nunca como texto base64 dentro del resultado de una consulta.
"""
import base64
import io
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from paginaweb.models import AsesorPerfil, PaginawebProducto, PaginawebSetting
from paginaweb.serializers import CATEGORIES, PaginawebProductoSerializer

CODIGO = {'.html', '.css', '.js', '.jsx', '.py', '.json', '.svg', '.txt'}
IMAGENES = {'.jpg', '.jpeg', '.png', '.webp'}
CLAVES_PUBLICAS = {'heroTitle', 'heroSubtitle', 'aboutText', 'whatsapp', 'phone', 'email',
                  'hours', 'mapUrl', 'instagram', 'facebook', 'tiktok', 'youtube'}
MAX_IMAGEN = 6 * 1024 * 1024


def _raiz(proyecto):
    opciones = {'web':settings.ASISTENTE_WEB_ROOT, 'landing':settings.ASISTENTE_LANDING_ROOT,
                'gestion':settings.ASISTENTE_GESTION_WEB_ROOT, 'backend_web':settings.ASISTENTE_BACKEND_WEB_ROOT}
    if proyecto not in opciones:
        raise ValueError('Proyecto inválido. Elige web, landing, gestion o backend_web.')
    return Path(opciones[proyecto]).resolve()


def _archivos(proyecto):
    raiz = _raiz(proyecto)
    if not raiz.is_dir():
        return {}
    if proyecto == 'web':
        candidatos = list((raiz / 'public').rglob('*')) + [raiz / 'server.js', raiz / 'src/routes/public.js']
    elif proyecto == 'landing':
        candidatos = [raiz / n for n in ['index.html', 'styles.css', 'script.js']]
    elif proyecto == 'gestion':
        candidatos = list((raiz / 'src/pages/paginaweb').rglob('*')) + [raiz / 'src/services/paginawebService.js', raiz / 'src/utils/textoFormato.js']
    else:
        candidatos = [raiz / n for n in ['models.py', 'serializers.py', 'views.py', 'urls.py', 'image_utils.py']]
    archivos = {}
    for archivo in sorted(candidatos):
        relativo = archivo.relative_to(raiz)
        if any(p.startswith('.') for p in relativo.parts) or archivo.suffix.lower() not in CODIGO | IMAGENES:
            continue
        real = archivo.resolve()
        if real != archivo.absolute() or raiz not in real.parents or not real.is_file():
            continue
        archivos[relativo.as_posix()] = real
    return archivos


def _archivo(proyecto, nombre, extensiones):
    archivo = _archivos(proyecto).get(str(nombre))
    if not archivo or archivo.suffix.lower() not in extensiones:
        raise ValueError('Archivo no disponible. Elige una ruta del índice de la página web.')
    return archivo


def _numero(args, campo, defecto, minimo, maximo):
    valor = int(args.get(campo, defecto))
    if not minimo <= valor <= maximo:
        raise ValueError(f'{campo} debe estar entre {minimo} y {maximo}.')
    return valor


def _acotar(valor, longitud=1200):
    texto = json.dumps(valor, ensure_ascii=False, default=str) if not isinstance(valor, str) else valor
    return texto if len(texto) <= longitud else texto[:longitud] + '… [recortado]'


class _Contenido(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ocultos = 0
        self.textos, self.enlaces, self.imagenes, self.titulos, self.meta = [], [], [], [], []
        self.encabezado = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ['script', 'style', 'head']:
            self.ocultos += 1
        if tag == 'meta' and (a.get('name') or a.get('property')):
            self.meta.append({'nombre': a.get('name') or a.get('property'), 'contenido': a.get('content', '')})
        if self.ocultos:
            return
        if tag in ['h1', 'h2', 'h3']:
            self.encabezado = {'nivel': tag, 'texto': ''}
        if tag == 'a' and a.get('href'):
            self.enlaces.append(a['href'])
        if tag in ['img', 'video', 'source']:
            self.imagenes.append({k: v for k, v in a.items() if k in ['src', 'srcset', 'alt', 'poster', 'type']})

    def handle_endtag(self, tag):
        if tag in ['script', 'style', 'head']:
            self.ocultos = max(0, self.ocultos - 1)
        if self.encabezado and tag == self.encabezado['nivel']:
            self.titulos.append(self.encabezado)
            self.encabezado = None

    def handle_data(self, data):
        texto = ' '.join(data.split())
        if texto and not self.ocultos:
            self.textos.append(texto)
            if self.encabezado:
                self.encabezado['texto'] += (' ' if self.encabezado['texto'] else '') + texto


def consultar(args):
    proyecto, seccion = args.get('proyecto', 'web'), args.get('seccion', 'resumen')
    if seccion not in ['resumen', 'archivos', 'contenido', 'diseno', 'catalogo', 'asesores']:
        raise ValueError('Sección inválida.')
    archivos = _archivos(proyecto)
    resultado = {'proyecto': proyecto, 'consultado': timezone.now().isoformat(), 'solo_lectura': True,
                 'origen': 'Archivos locales del sitio y contenido público vigente del catálogo.',
                 'proyectos': {'web':'Sitio público', 'landing':'Página de enlaces', 'gestion':'Gestión web en la plataforma', 'backend_web':'API, modelos, validación y procesamiento de imágenes de la web'},
                 'sitio_publico': settings.PUBLIC_SITE_URL,
                 'alcance_visual': 'HTML, estilos e imágenes reales del sitio; no es una captura de la página renderizada.'}
    if seccion in ['resumen', 'archivos']:
        filtro = str(args.get('buscar', '')).lower()[:100]
        lista = [{'archivo': n, 'tipo': 'imagen' if p.suffix.lower() in IMAGENES else 'codigo', 'bytes': p.stat().st_size}
                 for n, p in archivos.items() if filtro in n.lower()]
        pagina = _numero(args, 'pagina', 1, 1, 1000)
        cantidad = 18 if seccion == 'resumen' else 45
        resultado.update(archivos=lista[(pagina-1)*cantidad:pagina*cantidad], total_archivos=len(lista),
                         pagina=pagina, hay_mas=pagina*cantidad < len(lista), codigo_disponible=bool(archivos))
        if not archivos:
            resultado['aviso'] = 'Los archivos del sitio no están instalados en este servidor. El catálogo público sigue disponible.'
    if seccion in ['resumen', 'contenido']:
        nombre = str(args.get('archivo', 'public/index.html' if proyecto == 'web' else 'index.html'))
        if nombre in archivos:
            documento = _archivo(proyecto, nombre, {'.html'}).read_text(encoding='utf-8')[:250_000]
            contenido = _Contenido()
            contenido.feed(documento)
            resultado['pagina'] = {'archivo': nombre, 'encabezados': contenido.titulos[:20],
                'texto': _acotar(' '.join(contenido.textos), 3500), 'seo': contenido.meta[:12],
                'enlaces': list(dict.fromkeys(contenido.enlaces))[:20], 'medios': contenido.imagenes[:12],
                'nota': 'El texto base puede ser reemplazado por la configuración y el catálogo dinámicos.'}
        elif seccion == 'contenido':
            raise ValueError('Página no disponible. Consulta primero el índice de archivos.')
        resultado['configuracion_publica'] = {o.key: _acotar(o.value, 1500)
            for o in PaginawebSetting.objects.filter(key__in=CLAVES_PUBLICAS)}
    if seccion in ['resumen', 'diseno']:
        css = '\n'.join(p.read_text(encoding='utf-8')[:500_000] for p in archivos.values() if p.suffix.lower() == '.css')
        resultado['diseno'] = {'colores': list(dict.fromkeys(re.findall(r'#[0-9a-fA-F]{3,8}\b', css)))[:25],
            'variables': [{'nombre': n, 'valor': v.strip()[:120]} for n, v in re.findall(r'(--[\w-]+)\s*:\s*([^;{}]+)', css)[:28]],
            'fuentes': list(dict.fromkeys(re.findall(r'font-family\s*:\s*([^;{}]+)', css)))[:8],
            'adaptacion_pantallas': list(dict.fromkeys(re.findall(r'@media\s*([^{}]+)', css)))[:12],
            'imagenes': [n for n, p in archivos.items() if p.suffix.lower() in IMAGENES][:35],
            'siguiente': 'Usa leer_codigo_pagina_web para estudiar los estilos y ver_imagen_pagina_web para ver una imagen real.'}
    if seccion == 'catalogo':
        pagina = _numero(args, 'pagina', 1, 1, 1000)
        qs = PaginawebProducto.objects.filter(active=True).order_by('-featured', 'name')
        if args.get('buscar'):
            q = str(args['buscar'])[:100]
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(category__icontains=q))
        if args.get('categoria'):
            qs = qs.filter(category=str(args['categoria'])[:100])
        cantidad = _numero(args, 'limite', 3, 1, 5)
        total = qs.count()
        datos = PaginawebProductoSerializer(qs[(pagina-1)*cantidad:pagina*cantidad], many=True).data
        resultado.update(productos=[{k: (v[:6] if isinstance(v, list) else v) if k in ['images', 'variants', 'featured', 'active'] else _acotar(v, 700)
            for k, v in p.items() if k not in ['short_description', 'created_at', 'updated_at']} for p in datos],
            total=total, pagina=pagina, hay_mas=pagina*cantidad < total, categorias=CATEGORIES)
    if seccion == 'asesores':
        resultado['asesores_publicados'] = list(AsesorPerfil.objects.filter(activo=True).values('nombre', 'cargo', 'slug', 'bio_corta', 'foto')[:30])
    return resultado


def leer_codigo(args):
    proyecto = args.get('proyecto', 'web')
    nombre = str(args.get('archivo', ''))
    archivo = _archivo(proyecto, nombre, CODIGO)
    if archivo.stat().st_size > 1024 * 1024:
        raise ValueError('Archivo demasiado grande para consultar su código.')
    desde = _numero(args, 'desde_linea', 1, 1, 100_000)
    cantidad = _numero(args, 'lineas', 100, 1, 160)
    lineas = archivo.read_text(encoding='utf-8').splitlines()
    seleccion, caracteres = [], 0
    for i, linea in enumerate(lineas[desde-1:desde-1+cantidad], desde):
        texto = f'{i}: {linea}'
        if len(texto) > 10_000:
            texto = texto[:10_000] + '… [línea recortada]'
        if caracteres + len(texto) > 11_000:
            break
        seleccion.append(texto)
        caracteres += len(texto) + 1
    siguiente = desde + len(seleccion)
    return {'proyecto': proyecto, 'archivo': nombre, 'desde_linea': desde, 'total_lineas': len(lineas),
            'codigo': '\n'.join(seleccion), 'siguiente_linea': siguiente if siguiente <= len(lineas) else None,
            'solo_lectura': True, 'origen': 'Archivo local vigente; puede diferir del sitio desplegado.'}


def _bytes_publicados(url):
    u = urlparse(str(url))
    if not u.scheme and not u.netloc:
        prefijo = next((p for p in ['/media/', '/uploads/'] if u.path.startswith(p)), None)
        if not prefijo:
            raise ValueError('Esta imagen no está disponible como archivo del catálogo.')
        raiz = Path(settings.MEDIA_ROOT).resolve()
        archivo = (raiz / u.path[len(prefijo):]).resolve()
        if raiz not in archivo.parents or not archivo.is_file() or archivo.stat().st_size > MAX_IMAGEN:
            raise ValueError('La imagen publicada no está disponible en este servidor.')
        return archivo.read_bytes()
    host = (u.hostname or '').lower()
    if u.scheme != 'https' or u.username or u.password or u.port not in [None, 443] or not (host == 'res.cloudinary.com' or host.endswith('.sirv.com')):
        raise ValueError('Solo se pueden ver archivos locales o imágenes publicadas en el CDN del sitio.')
    with requests.get(url, stream=True, timeout=(3, 7), allow_redirects=False) as r:
        if r.status_code != 200:
            raise ValueError('El CDN no devolvió la imagen publicada.')
        datos = bytearray()
        for parte in r.iter_content(65536):
            datos.extend(parte)
            if len(datos) > MAX_IMAGEN:
                raise ValueError('La imagen supera el tamaño permitido.')
        return bytes(datos)


def ver_imagen(args):
    proyecto = args.get('proyecto', 'web')
    if args.get('producto'):
        producto = PaginawebProducto.objects.filter(active=True).filter(Q(pk=str(args['producto'])) | Q(slug=str(args['producto']))).first()
        indice = _numero(args, 'indice', 0, 0, 30)
        if not producto or indice >= len(producto.images or []):
            raise ValueError('Producto publicado o imagen no encontrado.')
        nombre, datos = producto.images[indice], _bytes_publicados(producto.images[indice])
    else:
        nombre = str(args.get('archivo', ''))
        archivo = _archivo(proyecto, nombre, IMAGENES)
        if archivo.stat().st_size > MAX_IMAGEN:
            raise ValueError('La imagen supera el tamaño permitido.')
        datos = archivo.read_bytes()
    try:
        with Image.open(io.BytesIO(datos)) as original:
            if original.width * original.height > 32_000_000:
                raise ValueError('La imagen tiene demasiados píxeles.')
            dimensiones = {'ancho': original.width, 'alto': original.height}
            imagen = ImageOps.exif_transpose(original).convert('RGB')
            imagen.thumbnail((1400, 1400))
            salida = io.BytesIO()
            imagen.save(salida, format='JPEG', quality=82)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('El archivo no es una imagen legible.') from None
    return {'imagen': nombre, 'dimensiones_originales': dimensiones, 'solo_lectura': True,
            'tipo': 'Imagen real del sitio, no captura de una página renderizada.',
            '_imagenes': [{'mimeType': 'image/jpeg', 'data': base64.b64encode(salida.getvalue()).decode('ascii')} ]}
