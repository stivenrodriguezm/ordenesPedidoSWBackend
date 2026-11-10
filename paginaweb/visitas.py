"""Contador de visitas de la página web y de la landing de enlaces (2026-11-04).

POST /api/paginaweb/visitas/          público: registra una página vista o un clic.
GET  /api/paginaweb/admin/visitas/    Gestión Web: resumen y estadísticas del período.

El navegador manda el registro con `navigator.sendBeacon` como texto plano (así no
hay preflight de CORS ni se pierde el clic al salir de la página). No se guarda la
IP ni se usan cookies: el visitante es un identificador anónimo del navegador.
"""
import datetime
import json
import re
from urllib.parse import urlparse

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ordenes.permissions import check_feature_permission

from .models import PaginawebProducto, AsesorPerfil, VisitaWeb

ID_RE = re.compile(r'^[A-Za-z0-9-]{8,40}$')
ETIQUETA_RE = re.compile(r'[^a-z0-9._-]+')
BOT_RE = re.compile(r'bot|crawl|spider|slurp|headless|lighthouse|preview|phantom|puppeteer|playwright|python|curl|wget', re.I)
DIAS_MAXIMOS = 366

# Dominio de quien envía la visita → fuente legible. El orden importa: lo primero que coincide.
FUENTES = [
    ('instagram', ('instagram.com', 'ig.me')),
    ('facebook', ('facebook.com', 'fb.com', 'fb.me', 'messenger.com')),
    ('whatsapp', ('whatsapp.com', 'wa.me')),
    ('tiktok', ('tiktok.com',)),
    ('google', ('google.',)),
    ('bing', ('bing.com',)),
    ('youtube', ('youtube.com', 'youtu.be')),
]
DOMINIOS_PROPIOS = ('muebleslottus.com', 'stivenrodriguezm.github.io', 'localhost', '127.0.0.1')


class TextoJSONParser(BaseParser):
    """sendBeacon manda el JSON como text/plain (petición simple, sin preflight)."""
    media_type = 'text/plain'

    def parse(self, stream, media_type=None, parser_context=None):
        try:
            return json.loads(stream.read().decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return {}


def _host(url):
    try:
        return (urlparse(url).hostname or '').lower().removeprefix('www.')
    except ValueError:
        return ''


def _fuente(referente_host, utm, sitio):
    """Fuente de la sesión: utm_source si viene (los enlaces de la bio lo pueden
    llevar), si no el dominio de origen. 'landing' = llegó a la web desde la landing."""
    utm = ETIQUETA_RE.sub('', (utm or '').lower())[:20]
    if utm:
        return utm
    if not referente_host:
        return 'directo'
    if referente_host.startswith('landing.muebleslottus.com') and sitio == 'web':
        return 'landing'
    if any(referente_host == d or referente_host.endswith('.' + d) for d in DOMINIOS_PROPIOS):
        return 'interna'
    for fuente, dominios in FUENTES:
        if any(d in referente_host for d in dominios):
            return fuente
    return 'otro'


def _dispositivo(ua):
    ua = ua or ''
    if re.search(r'iPad|Tablet', ua) or ('Android' in ua and 'Mobile' not in ua):
        return 'tablet'
    if re.search(r'Mobi|iPhone|Android', ua):
        return 'celular'
    return 'computador'


def _ruta(path):
    """'/producto/sofa-x' → ('/producto', 'sofa-x'); '/catalogo.html' → '/catalogo'."""
    path = (path or '/').split('?')[0].split('#')[0].strip().lower()
    partes = [p for p in path.split('/') if p]
    if not partes:
        return '/', ''
    partes[0] = partes[0].removesuffix('.html')
    if partes[0] in ('index', ''):
        return '/', ''
    if partes[0] in ('producto', 'asesor') and len(partes) > 1:
        return f'/{partes[0]}', ETIQUETA_RE.sub('', partes[1])[:120]
    return '/' + '/'.join(partes)[:119], ''


class RegistrarVisitaView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, TextoJSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'visitas'

    def post(self, request):
        datos = request.data if isinstance(request.data, dict) else {}
        ua = request.META.get('HTTP_USER_AGENT', '')
        sitio, tipo = datos.get('sitio'), datos.get('tipo', 'pagina')
        visitante, sesion = str(datos.get('visitante') or ''), str(datos.get('sesion') or '')
        if (sitio not in dict(VisitaWeb.SITIOS) or tipo not in dict(VisitaWeb.TIPOS)
                or not ID_RE.match(visitante) or not ID_RE.match(sesion)):
            return Response({'error': 'Registro de visita inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        if not ua or BOT_RE.search(ua):
            return Response(status=status.HTTP_204_NO_CONTENT)

        ruta, etiqueta = _ruta(str(datos.get('ruta') or '/'))
        if tipo == 'clic':
            etiqueta = ETIQUETA_RE.sub('', str(datos.get('etiqueta') or '').lower())[:120]
            if not etiqueta:
                return Response({'error': 'Falta qué se tocó.'}, status=status.HTTP_400_BAD_REQUEST)
        entrada = tipo == 'pagina' and bool(datos.get('entrada'))
        referente = _host(str(datos.get('referente') or ''))[:120] if entrada else ''
        ahora = timezone.localtime()
        VisitaWeb.objects.create(
            sitio=sitio, tipo=tipo, ruta=ruta, etiqueta=etiqueta,
            visitante=visitante, sesion=sesion,
            entrada=entrada, visitante_nuevo=entrada and bool(datos.get('nuevo')),
            fuente=_fuente(referente, datos.get('utm'), sitio) if entrada else '',
            referente=referente, dispositivo=_dispositivo(ua),
            fecha=ahora.date(), hora=ahora.hour,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _fecha(texto, defecto):
    try:
        return datetime.date.fromisoformat(texto) if texto else defecto
    except ValueError:
        return None


def _totales(qs):
    """Cifras por sitio de un queryset ya filtrado por fechas."""
    filas = qs.values('sitio').annotate(
        visitas=Count('id', filter=Q(tipo='pagina')),
        sesiones=Count('id', filter=Q(entrada=True)),
        visitantes=Count('visitante', distinct=True, filter=Q(tipo='pagina')),
        nuevos=Count('id', filter=Q(visitante_nuevo=True)),
        clics=Count('id', filter=Q(tipo='clic')),
        clics_whatsapp=Count('id', filter=Q(tipo='clic', etiqueta__startswith='whatsapp')),
    )
    vacio = {'visitas': 0, 'sesiones': 0, 'visitantes': 0, 'nuevos': 0, 'clics': 0, 'clics_whatsapp': 0}
    res = {s: dict(vacio) for s, _ in VisitaWeb.SITIOS}
    for f in filas:
        res[f.pop('sitio')] = f
    return res


def _agrupar(qs, campo, metrica='id', distinct=False, limite=None):
    filas = qs.values('sitio', campo).annotate(n=Count(metrica, distinct=distinct)).order_by('-n')
    res = {s: [] for s, _ in VisitaWeb.SITIOS}
    for f in filas:
        if limite is None or len(res[f['sitio']]) < limite:
            res[f['sitio']].append({'clave': f[campo], 'n': f['n']})
    return res


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, check_feature_permission('GESTION_WEB')])
def resumen_visitas(request):
    """Resumen del período [desde, hasta] (por defecto los últimos 30 días) con
    comparación contra el período anterior de la misma duración."""
    hoy = timezone.localdate()
    hasta = _fecha(request.query_params.get('hasta'), hoy)
    desde = _fecha(request.query_params.get('desde'), hoy - datetime.timedelta(days=29))
    if not desde or not hasta or desde > hasta:
        return Response({'error': 'Rango de fechas inválido.'}, status=status.HTTP_400_BAD_REQUEST)
    if (hasta - desde).days >= DIAS_MAXIMOS:
        return Response({'error': f'El rango máximo es de {DIAS_MAXIMOS} días.'}, status=status.HTTP_400_BAD_REQUEST)
    duracion = hasta - desde + datetime.timedelta(days=1)

    periodo = VisitaWeb.objects.filter(fecha__range=(desde, hasta))
    paginas = periodo.filter(tipo='pagina')
    entradas = periodo.filter(entrada=True)

    por_dia = {}
    for f in paginas.values('fecha', 'sitio').annotate(visitas=Count('id'), visitantes=Count('visitante', distinct=True)):
        dia = por_dia.setdefault(f['fecha'], {s: {'visitas': 0, 'visitantes': 0} for s, _ in VisitaWeb.SITIOS})
        dia[f['sitio']] = {'visitas': f['visitas'], 'visitantes': f['visitantes']}
    dias = []
    d = desde
    while d <= hasta:
        vacio = {s: {'visitas': 0, 'visitantes': 0} for s, _ in VisitaWeb.SITIOS}
        dias.append({'fecha': d.isoformat(), **por_dia.get(d, vacio)})
        d += datetime.timedelta(days=1)

    por_hora = {s: [0] * 24 for s, _ in VisitaWeb.SITIOS}
    for f in paginas.values('sitio', 'hora').annotate(n=Count('id')):
        por_hora[f['sitio']][f['hora']] = f['n']

    # Productos y asesores más vistos, con su nombre (el slug solo si ya no existe).
    vistos = paginas.filter(sitio='web', ruta__in=('/producto', '/asesor')).exclude(etiqueta='')
    top_productos = list(vistos.filter(ruta='/producto').values('etiqueta')
                         .annotate(visitas=Count('id'), visitantes=Count('visitante', distinct=True))
                         .order_by('-visitas')[:10])
    nombres = dict(PaginawebProducto.objects.filter(slug__in=[p['etiqueta'] for p in top_productos])
                   .values_list('slug', 'name'))
    for p in top_productos:
        p['nombre'] = nombres.get(p['etiqueta'], p['etiqueta'])
    top_asesores = list(vistos.filter(ruta='/asesor').values('etiqueta')
                        .annotate(visitas=Count('id')).order_by('-visitas')[:10])
    nombres = dict(AsesorPerfil.objects.filter(slug__in=[a['etiqueta'] for a in top_asesores])
                   .values_list('slug', 'nombre'))
    for a in top_asesores:
        a['nombre'] = nombres.get(a['etiqueta'], a['etiqueta'])

    historico = dict(VisitaWeb.objects.filter(tipo='pagina').values_list('sitio').annotate(n=Count('id')))
    primera = VisitaWeb.objects.order_by('fecha').values_list('fecha', flat=True).first()
    return Response({
        'desde': desde.isoformat(),
        'hasta': hasta.isoformat(),
        'totales': _totales(periodo),
        'anterior': _totales(VisitaWeb.objects.filter(fecha__range=(desde - duracion, desde - datetime.timedelta(days=1)))),
        'hoy': _totales(VisitaWeb.objects.filter(fecha=hoy)),
        'historico': {s: historico.get(s, 0) for s, _ in VisitaWeb.SITIOS},
        'desde_historico': primera.isoformat() if primera else None,
        'por_dia': dias,
        'por_hora': por_hora,
        'paginas': _agrupar(paginas, 'ruta', limite=12),
        'fuentes': _agrupar(entradas.exclude(fuente='interna'), 'fuente'),
        'dispositivos': _agrupar(entradas, 'dispositivo'),
        'clics': _agrupar(periodo.filter(tipo='clic'), 'etiqueta', limite=15),
        'productos': top_productos,
        'asesores': top_asesores,
    })
