import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
import uuid

from django.db import models, transaction
from django.db.models import Q, Prefetch
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ordenes.models import Cliente, Venta, LineaVenta
from ordenes.permissions import check_feature_permission, tiene_permiso_codigo
from ordenes.serializers import ClienteSerializer
from ordenes.servicios import auditar, siguiente_consecutivo
from paginaweb.sirv import upload_to_sirv, SirvUploadError

from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante, EspecialLinea,
    Cotizacion, LineaCotizacion, EspecialCatalogo,
)
from .serializers import (
    CategoriaListaSerializer, CategoriaListaPublicSerializer, GrupoTelaSerializer, MultiplicadorSerializer, OrdenVariantesSerializer, AgrupacionNuevaSerializer,
    LineaProductoSerializer, LineaProductoResumenSerializer, VarianteProductoSerializer,
    CargoVarianteSerializer, PrecioVarianteSerializer, LineaCatalogoSerializer, EspecialLineaSerializer,
    CotizacionSerializer, LineaCotizacionSerializer, EspecialCatalogoSerializer,
)
from .especiales import aplicar_configurado, archivar_historico
from . import cache_catalogo
from .services import (
    impacto_categoria, impacto_multiplicador, impacto_grupo_tela, obtener_grupos_tela, calcular_precio, precios_por_variante,
    opcionales_de_variante, obtener_multiplicador_general, establecer_multiplicador_general,
    asignar_multiplicador_masivo, simular_multiplicador, validar_descuento_documento, costo_lista, tope_descuento,
    PREFETCH_JUEGOS, guardar_componentes, simular_componentes, ordenar_variantes, crear_agrupacion, aplicar_especial,
)

logger = logging.getLogger(__name__)


ACCIONES_LECTURA = {'list', 'retrieve', 'impacto', 'biblioteca'}


def _permisos_por_accion(view, permiso_lectura):
    """Mapa explícito (H08): solo las acciones de lectura conocidas usan el
    permiso de lectura; cualquier otra acción —incluidas las personalizadas
    como asignar-multiplicador— exige EDITAR_LISTA_PRECIOS."""
    if view.action in ACCIONES_LECTURA:
        return [IsAuthenticated(), check_feature_permission(permiso_lectura)()]
    return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]


def _precios_context():
    """Contexto compartido por los serializers que calculan precios: el
    multiplicador general y la lista de grupos de tela, cada uno resuelto
    una sola vez por request (ver services.obtener_multiplicador_general /
    obtener_grupos_tela) en vez de una consulta por cada variante anidada."""
    general_obj = Multiplicador.objects.filter(es_general=True).first()
    return {
        'multiplicador_general': general_obj.valor if general_obj else None,
        'multiplicador_general_obj': general_obj,
        'grupos': obtener_grupos_tela(),
    }


def _aplicar_decorativos(lineas_info, lineas_instancias):
    """Descuenta de cada decorativo lo que cubren los «Decorativos x2» de los demás productos
    de la cotización (misma regla que en ventas). Devuelve el total incluido."""
    from .decorativos import calcular_incluidos
    incluidos = calcular_incluidos([{'clave': i, 'variante': info['variante_obj'], 'grupo': info['grupo_obj'], 'cantidad': info['cantidad']}
                                    for i, info in enumerate(lineas_info)])
    total = Decimal(0)
    for i, r in incluidos.items():
        valor = min(r['valor'], lineas_instancias[i]['subtotal'])
        lineas_instancias[i]['incluido'] = valor
        lineas_instancias[i]['subtotal'] -= valor
        lineas_info[i]['subtotal'] -= valor
        total += valor
    return total


def _contexto_catalogo():
    from .decorativos import grupos_incluidos, linea_decorativos
    linea = linea_decorativos()
    return {**_precios_context(), 'grupos_incluidos': grupos_incluidos(), 'linea_decorativos': linea.pk if linea else None}


class CategoriaListaViewSet(viewsets.ModelViewSet):
    """Categorías = tipo de producto — solo etiqueta, no define ningún
    precio (el precio por grupo es global, ver GrupoTela). Tampoco tienen
    multiplicador — eso vive en Multiplicador, completamente aparte."""
    queryset = CategoriaLista.objects.all()
    serializer_class = CategoriaListaSerializer

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    @action(detail=True, methods=['get'])
    def impacto(self, request, pk=None):
        categoria = self.get_object()
        return Response(impacto_categoria(categoria))


class MultiplicadorViewSet(viewsets.ModelViewSet):
    """Catálogo de multiplicadores con nombre libre (ver docstring del
    modelo) — el margen ya no depende de la categoría, es una entidad
    propia que el administrador crea y nombra como quiera."""
    queryset = Multiplicador.objects.all()
    serializer_class = MultiplicadorSerializer

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    def perform_create(self, serializer):
        instance = serializer.save()
        if instance.es_general:
            establecer_multiplicador_general(instance)
        elif not Multiplicador.objects.filter(es_general=True).exclude(pk=instance.pk).exists():
            # El primer multiplicador que se crea queda como general por
            # defecto — nunca puede quedar el catálogo sin ninguno general.
            establecer_multiplicador_general(instance)

    def perform_update(self, serializer):
        antes = {'valor': str(serializer.instance.valor), 'es_general': serializer.instance.es_general}
        instance = serializer.save()
        if instance.es_general:
            establecer_multiplicador_general(instance)
        auditar(self.request.user, 'precios.multiplicador', instance, {
            'antes': antes, 'despues': {'valor': str(instance.valor), 'es_general': instance.es_general},
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.es_general:
            return Response(
                {'error': 'No se puede eliminar el multiplicador general. Marca otro como general primero.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'error': 'No se puede eliminar: hay variantes usando este multiplicador. Reasígnalas primero.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['get'])
    def impacto(self, request, pk=None):
        multiplicador = self.get_object()
        return Response(impacto_multiplicador(multiplicador))

    @action(detail=True, methods=['post'], url_path='simular')
    def simular(self, request, pk=None):
        multiplicador = self.get_object()
        nuevo_valor = request.data.get('nuevo_valor')
        if nuevo_valor is None:
            return Response({'error': 'Debes especificar el nuevo valor del multiplicador.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            nuevo_valor_dec = Decimal(str(nuevo_valor))
            if nuevo_valor_dec <= 0:
                return Response({'error': 'El multiplicador debe ser mayor a cero.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'Valor de multiplicador inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        res = simular_multiplicador(multiplicador, nuevo_valor_dec)
        return Response(res)


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_LISTA_PRECIOS')])
def categorias_publicas(request):
    """GET /api/listaprecios/categorias-publicas/ — nombre/slug/orden solo,
    para los chips de filtro del catálogo de vendedor. No expone margen."""
    return Response(cache_catalogo.obtener('categorias', lambda: CategoriaListaPublicSerializer(CategoriaLista.objects.filter(activo=True), many=True).data))


class GrupoTelaViewSet(viewsets.ModelViewSet):
    queryset = GrupoTela.objects.all()
    serializer_class = GrupoTelaSerializer

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_LISTA_PRECIOS')

    @action(detail=True, methods=['get'])
    def impacto(self, request, pk=None):
        grupo = self.get_object()
        return Response(impacto_grupo_tela(grupo))


class LineaProductoViewSet(viewsets.ModelViewSet):
    """Vista de administración (incluye costos anidados de las variantes)."""
    queryset = LineaProducto.objects.prefetch_related(
        Prefetch('variantes', queryset=VarianteProducto.objects.select_related('categoria', 'multiplicador')),
        'variantes__cargos__especial', 'variantes__precios', 'variantes__precios__grupo',
        *[f'variantes__{p}' for p in PREFETCH_JUEGOS], 'especiales__cargos__variante__multiplicador',
    ).all()
    serializer_class = LineaProductoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['activo']
    # Busca por nombre de la línea/colección (ej. "Detroit") o por nombre de
    # cualquiera de sus variantes (ej. "Sofá 3p.") — cualquiera de las dos
    # formas en que el admin suele buscar un producto.
    search_fields = ['nombre', 'variantes__nombre']

    def get_queryset(self):
        qs = (LineaProducto.objects.prefetch_related(Prefetch('variantes', queryset=VarianteProducto.objects.select_related('categoria')))
              if self._es_resumen() else self.queryset)
        categoria = self.request.query_params.get('categoria')
        if categoria:
            qs = qs.filter(variantes__categoria=categoria)
        # distinct() siempre: tanto el filtro por categoría como la búsqueda
        # por variantes__nombre atraviesan una relación a-muchos y pueden
        # duplicar filas de LineaProducto sin esto.
        return qs.distinct()

    def _es_resumen(self):
        return self.action == 'list' and self.request.query_params.get('resumen') == '1'

    def get_serializer_class(self):
        return LineaProductoResumenSerializer if self._es_resumen() else self.serializer_class

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    def get_serializer_context(self):
        # Precarga los grupos de tela y el multiplicador general en un solo
        # query cada uno — evita que cada variante/precio anidado dispare
        # su propia consulta (ver services.calcular_precio).
        context = super().get_serializer_context()
        if not self._es_resumen():
            context.update(_precios_context())
        return context

    def perform_create(self, serializer):
        data = serializer.validated_data
        nombre = data['nombre']
        slug = data.get('slug')
        if not slug:
            from django.utils.text import slugify
            slug = slugify(nombre) or 'linea'
            base_slug = slug
            count = 1
            while LineaProducto.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{count}"
                count += 1
        serializer.save(slug=slug)

    @action(detail=True, methods=['post'], url_path='orden-variantes')
    def orden_variantes(self, request, pk=None):
        entrada = OrdenVariantesSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        linea = self.get_object()
        orden = ordenar_variantes(linea, entrada.validated_data['variantes'], entrada.validated_data['orden_anterior'])
        auditar(request.user, 'precios.orden_variantes', linea, {'variantes': orden})
        return Response({'variantes': orden})

    @action(detail=True, methods=['post'], url_path='agrupaciones')
    def agrupaciones(self, request, pk=None):
        entrada = AgrupacionNuevaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        juego = crear_agrupacion(self.get_object(), **entrada.validated_data)
        auditar(request.user, 'precios.crear_agrupacion', juego)
        juego = VarianteProductoViewSet.queryset.get(pk=juego.pk)
        return Response(VarianteProductoSerializer(juego, context=self.get_serializer_context()).data, status=201)

    @action(detail=True, methods=['post'], url_path='simular-agrupacion')
    def simular_agrupacion(self, request, pk=None):
        # Identificador transitorio: permite usar los managers precargados sin guardar una fila.
        juego = VarianteProducto(pk=0, linea=self.get_object(), costo_base=0)
        juego._prefetched_objects_cache = {'cargos': [], 'precios': []}
        contexto = self.get_serializer_context()
        return Response(simular_componentes(juego, request.data.get('componentes'), contexto['grupos'], contexto['multiplicador_general']))


class VarianteProductoViewSet(viewsets.ModelViewSet):
    queryset = VarianteProducto.objects.select_related('linea', 'categoria', 'multiplicador').prefetch_related('cargos__especial', 'precios__grupo', *PREFETCH_JUEGOS).all()
    serializer_class = VarianteProductoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['linea', 'categoria', 'multiplicador']

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(_precios_context())
        return context

    def update(self, request, *args, **kwargs):
        # DRF descarta todos los prefetch después del save. Recargar una sola
        # vez evita una consulta por grupo/cargo al representar la respuesta.
        instancia = self.get_object()
        serializer = self.get_serializer(instancia, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        actualizada = self.get_queryset().get(pk=instancia.pk)
        return Response(self.get_serializer(actualizada).data)

    @transaction.atomic
    def perform_create(self, serializer):
        linea = serializer.validated_data['linea']
        LineaProducto.objects.select_for_update().get(pk=linea.pk)
        if 'orden' not in serializer.validated_data:
            ultimo = VarianteProducto.objects.filter(linea=linea).aggregate(valor=models.Max('orden'))['valor']
            serializer.save(orden=0 if ultimo is None else ultimo + 1)
        else:
            serializer.save()

    @action(detail=True, methods=['put'], url_path='componentes')
    def componentes(self, request, pk=None):
        """PUT /api/listaprecios/variantes/{id}/componentes/ — {componentes: [{variante, cantidad}]}.
        Convierte la variante en un juego (lista vacía = vuelve a ser un producto normal)."""
        juego = self.get_object()
        guardar_componentes(juego, request.data.get('componentes'))
        auditar(request.user, 'precios.juego_componentes', juego, {'componentes': request.data['componentes']})
        juego = self.get_queryset().get(pk=juego.pk)
        return Response(self.get_serializer(juego).data)

    @action(detail=True, methods=['post'], url_path='simular-componentes')
    def simular_componentes(self, request, pk=None):
        contexto = self.get_serializer_context()
        return Response(simular_componentes(self.get_object(), request.data.get('componentes'),
                                           contexto['grupos'], contexto['multiplicador_general']))

    @action(detail=False, methods=['post'], url_path='asignar-multiplicador')
    def asignar_multiplicador(self, request):
        """POST /api/listaprecios/variantes/asignar-multiplicador/
        body: {multiplicador: id|null, categoria: id?, linea: id?, variante_ids: [..]?}
        Asigna en bloque — "por producto, categoría y así" — al menos uno
        de categoria/linea/variante_ids es obligatorio."""
        multiplicador_id = request.data.get('multiplicador')
        if multiplicador_id:
            if not Multiplicador.objects.filter(id=multiplicador_id).exists():
                return Response({'error': 'Multiplicador no encontrado.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            actualizadas = asignar_multiplicador_masivo(
                multiplicador_id=multiplicador_id or None,
                categoria_id=request.data.get('categoria'),
                linea_id=request.data.get('linea'),
                variante_ids=request.data.get('variante_ids'),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        auditar(request.user, 'precios.asignar_multiplicador', Multiplicador(pk=multiplicador_id or 0), {
            'categoria': request.data.get('categoria'), 'linea': request.data.get('linea'),
            'variante_ids': request.data.get('variante_ids'), 'actualizadas': actualizadas,
        })
        return Response({'ok': True, 'actualizadas': actualizadas})


class CargoVarianteViewSet(viewsets.ModelViewSet):
    queryset = CargoVariante.objects.all()
    serializer_class = CargoVarianteSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['variante']

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')


class EspecialLineaViewSet(viewsets.ModelViewSet):
    """Variantes especiales de un juego (línea): se aplican como opcionales a sus variantes.
    Crear/editar acepta `aplicaciones`: [{variante, valor}] (sin ella, al crear aplica a todas)."""
    queryset = EspecialLinea.objects.select_related('linea').prefetch_related('cargos__variante__multiplicador', 'cargos__especial').all()
    serializer_class = EspecialLineaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['linea']

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(_precios_context())
        return context

    @action(detail=False, methods=['get'])
    def biblioteca(self, request):
        return Response(EspecialCatalogoSerializer(EspecialCatalogo.objects.all(), many=True).data)

    def perform_create(self, serializer):
        with transaction.atomic():
            config = serializer.validated_data.get('configuracion')
            if config:
                especial = serializer.save(valor=Decimal(config['costo_base']))
                aplicar_configurado(especial, self.request.data.get('aplicaciones'))
                auditar(self.request.user, 'precios.especial_creada', especial, {'nombre': especial.nombre})
                return
            diferencia = serializer.validated_data.pop('diferencia_precio', None)
            especial = serializer.save(**({'valor': diferencia} if diferencia is not None else {}))
            aplicar_especial(especial, self.request.data.get('aplicaciones'), diferencia_precio=diferencia is not None)
            archivar_historico(especial, serializer.context.get('multiplicador_general'))
            auditar(self.request.user, 'precios.especial_creada', especial, {'nombre': especial.nombre})

    def perform_update(self, serializer):
        with transaction.atomic():
            config = serializer.validated_data.get('configuracion', serializer.instance.configuracion)
            if config:
                especial = serializer.save(valor=Decimal(config['costo_base']))
                aplicar_configurado(especial, self.request.data.get('aplicaciones'))
                auditar(self.request.user, 'precios.especial_editada', especial, {'nombre': especial.nombre})
                return
            diferencia = serializer.validated_data.pop('diferencia_precio', None)
            especial = serializer.save(**({'valor': diferencia} if diferencia is not None else {}))
            aplicaciones = self.request.data.get('aplicaciones')
            if aplicaciones is None:  # renombrar o cambiar valor por defecto: conserva a quién aplica
                aplicaciones = [{'variante': c.variante_id,
                                 ('diferencia_precio' if c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO else 'valor'): c.valor}
                                for c in especial.cargos.all()]
            aplicar_especial(especial, aplicaciones, diferencia_precio=diferencia is not None)
            archivar_historico(especial, serializer.context.get('multiplicador_general'))
            auditar(self.request.user, 'precios.especial_editada', especial, {'nombre': especial.nombre})

    def perform_destroy(self, instance):
        auditar(self.request.user, 'precios.especial_eliminada', instance, {'nombre': instance.nombre})
        instance.delete()


class PrecioVarianteViewSet(viewsets.ModelViewSet):
    queryset = PrecioVariante.objects.select_related('grupo', 'variante').all()
    serializer_class = PrecioVarianteSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['variante']

    def get_permissions(self):
        return _permisos_por_accion(self, 'VER_COSTOS_LISTA_PRECIOS')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(_precios_context())
        return context


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_LISTA_PRECIOS')])
def catalogo(request):
    """GET /api/listaprecios/catalogo/ — vista de vendedor. Parámetros:
    categoria (slug del tipo de producto — Salas, Poltronas...), q (búsqueda).
    Nunca incluye costo_base, metraje_tela ni cargos crudos."""
    qs = LineaProducto.objects.filter(activo=True).prefetch_related(
        Prefetch('variantes', queryset=VarianteProducto.objects.select_related('categoria', 'multiplicador')),
        'variantes__precios', 'variantes__precios__grupo', 'variantes__cargos__especial',
        *[f'variantes__{p}' for p in PREFETCH_JUEGOS],
    )

    categoria_slug = request.GET.get('categoria')
    q = request.GET.get('q')

    if not categoria_slug and not q:
        # El catálogo completo es igual para todos los vendedores: va desde la caché.
        return Response(cache_catalogo.obtener('catalogo', lambda: LineaCatalogoSerializer(qs, many=True, context=_contexto_catalogo()).data))

    if categoria_slug:
        qs = qs.filter(variantes__categoria__slug=categoria_slug).distinct()
    if q:
        needle = q.strip()
        qs = qs.filter(
            Q(nombre__icontains=needle) | Q(notas__icontains=needle) | Q(variantes__notas__icontains=needle)
        ).distinct()

    serializer = LineaCatalogoSerializer(qs, many=True, context=_contexto_catalogo())
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_LISTA_PRECIOS')])
def calcular_precio_variante(request, variante_id):
    """GET /api/listaprecios/variantes/<id>/precio/?grupo=<id>&opcionales=1,2,3
    Recalcula el precio de una variante en vivo con los cargos opcionales
    que el vendedor haya activado al cotizar (ej. transporte, tomacorriente).
    Nunca expone costo_base/metraje_tela/cargos fijos — solo el precio final
    y el detalle de los opcionales que sí se incluyeron."""
    variante = (
        VarianteProducto.objects.select_related('categoria', 'linea', 'multiplicador')
        .prefetch_related('cargos__especial', 'precios', 'precios__grupo', *PREFETCH_JUEGOS)
        .filter(id=variante_id, linea__activo=True).first()
    )
    if variante is None:
        return Response({'error': 'Variante no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    try:
        grupo_id = int(request.GET['grupo']) if request.GET.get('grupo') else None
    except (ValueError, TypeError):
        return Response({'error': 'Grupo de tela inválido'}, status=status.HTTP_400_BAD_REQUEST)

    disponibles = precios_por_variante(variante)
    if not any(fila['grupo'] == grupo_id for fila in disponibles):
        return Response({'error': 'Elige un grupo de tela disponible para este producto.'}, status=status.HTTP_400_BAD_REQUEST)
    grupo = GrupoTela.objects.filter(id=grupo_id).first() if grupo_id is not None else None

    opcionales_raw = request.GET.get('opcionales', '')
    try:
        opcionales_ids = {int(x) for x in opcionales_raw.split(',') if x.strip()}
    except ValueError:
        return Response({'error': 'Parámetro opcionales inválido'}, status=status.HTTP_400_BAD_REQUEST)

    disponibles_opcionales = opcionales_de_variante(variante, grupo=grupo)
    if not opcionales_ids.issubset({o['id'] for o in disponibles_opcionales}):
        return Response({'error': 'Algún adicional ya no está disponible para este producto.'}, status=status.HTTP_400_BAD_REQUEST)

    precio = calcular_precio(variante, grupo, opcionales_ids=opcionales_ids)
    incluidos = [o for o in disponibles_opcionales if o['id'] in opcionales_ids]
    return Response({'precio': precio, 'opcionales_incluidos': incluidos})


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('EDITAR_LISTA_PRECIOS')])
def upload_foto(request):
    """POST /api/listaprecios/upload-foto/ — sube foto(s) de una línea a
    Sirv, mismo flujo que paginaweb.admin_upload_image."""
    from paginaweb.image_utils import InvalidImageError, validar_archivo_imagen
    files = request.FILES.getlist('images') or request.FILES.getlist('file')
    if not files:
        return Response({"error": "No se enviaron archivos"}, status=status.HTTP_400_BAD_REQUEST)
    if len(files) > 10:
        return Response({"error": "Máximo 10 imágenes por envío."}, status=status.HTTP_400_BAD_REQUEST)

    # Validar todas antes de subir ninguna: formato real por contenido (no la
    # extensión ni el content-type del cliente), tamaño y dimensiones (H30).
    validadas = []
    for f in files:
        try:
            validadas.append(validar_archivo_imagen(f))
        except InvalidImageError as e:
            return Response({"error": f"{f.name}: {e}"}, status=status.HTTP_400_BAD_REQUEST)

    uploaded_urls = []
    for file_bytes, ext, content_type in validadas:
        filename = f"listaprecios/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        try:
            url = upload_to_sirv(file_bytes, filename, content_type)
        except SirvUploadError:
            logger.exception("Error subiendo foto de lista de precios a Sirv")
            return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)
        uploaded_urls.append(url)

    return Response({"ok": True, "urls": uploaded_urls, "url": uploaded_urls[0] if uploaded_urls else None})


# ------------------------------------------------------------------
# Cotizaciones del servidor (P09-01 / F01) y conversión a venta (P09-04)
# ------------------------------------------------------------------

class CotizacionViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar cotizaciones persistentes del servidor (P09-01 / F01).
    Soporta borradores, emisión, aceptación y conversión atómica a venta (P09-04).
    Control de concurrencia optimista mediante el campo `version`."""
    queryset = Cotizacion.objects.all().prefetch_related('lineas', 'cliente')
    serializer_class = CotizacionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['numero', 'cliente_nombre', 'cliente_documento', 'asesor_nombre']
    filterset_fields = ['estado']

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['ver_margenes'] = tiene_permiso_codigo(self.request, 'VER_MARGENES')
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        # Administrador y VER_TODAS_VENTAS ven todas las cotizaciones
        if getattr(user, 'role', '') == 'administrador' or tiene_permiso_codigo(self.request, 'VER_TODAS_VENTAS'):
            return qs
        if getattr(user, 'role', '') == 'vendedor' or tiene_permiso_codigo(self.request, 'VER_PROPIAS_VENTAS'):
            return qs.filter(asesor=user)
        return qs

    def perform_create(self, serializer):
        lineas_data = self.request.data.get('lineas', [])
        if not lineas_data:
            raise serializers.ValidationError({"lineas": "Una cotización requiere al menos un producto o línea."})

        with transaction.atomic():
            max_id = Cotizacion.objects.aggregate(m=models.Max('id'))['m'] or 1000
            num_consecutivo = siguiente_consecutivo('cotizacion', 1001, max_id)
            numero = f"COT-{num_consecutivo}"

            user = self.request.user
            asesor_nombre = user.get_full_name() or user.first_name or user.username

            cliente = serializer.validated_data.get('cliente')
            cliente_nombre = serializer.validated_data.get('cliente_nombre') or (cliente.nombre if cliente else '')
            fecha_vencimiento = serializer.validated_data.get('fecha_vencimiento') or (timezone.localdate() + datetime.timedelta(days=15))

            # Resolver variantes y grupos para validar tope de descuento y costo estimado congelado
            variante_ids = [l.get('variante') or l.get('variante_id') for l in lineas_data if l.get('variante') or l.get('variante_id')]
            variantes_map = {v.id: v for v in VarianteProducto.objects.filter(id__in=variante_ids).select_related('linea').prefetch_related('cargos__especial', 'precios', *PREFETCH_JUEGOS)}
            grupo_ids = [l.get('grupo_tela') or l.get('grupoId') for l in lineas_data if l.get('grupo_tela') or l.get('grupoId')]
            grupos_map = {g.id: g for g in GrupoTela.objects.filter(id__in=grupo_ids)}

            # Calcular subtotales desde los ítems enviados
            subtotal = Decimal('0.00')
            lineas_instancias = []
            lineas_info = []
            for l in lineas_data:
                cant = max(1, int(l.get('cantidad', 1)))
                pu = Decimal(str(l.get('precio_unitario', 0)))
                linea_subt = (pu * cant).quantize(Decimal('0.01'))
                subtotal += linea_subt

                v_id = l.get('variante') or l.get('variante_id')
                v_obj = variantes_map.get(int(v_id)) if v_id else None
                g_id = l.get('grupo_tela') or l.get('grupoId')
                g_obj = grupos_map.get(int(g_id)) if g_id else None

                costo_est = costo_lista(v_obj, g_obj, l.get('opcionales', [])) if v_obj else None

                lineas_info.append({
                    'subtotal': linea_subt,
                    'variante_obj': v_obj,
                    'grupo_obj': g_obj,
                    'cantidad': cant,
                })
                lineas_instancias.append({
                    'variante_id': v_obj.id if v_obj else None,
                    'linea_nombre': l.get('linea_nombre') or l.get('lineaNombre', 'Línea'),
                    'variante_nombre': l.get('variante_nombre') or l.get('varianteNombre', 'Producto'),
                    'categoria_nombre': l.get('categoria_nombre') or l.get('categoriaNombre', ''),
                    'grupo_tela_id': g_obj.id if g_obj else None,
                    'grupo_nombre': l.get('grupo_nombre') or l.get('grupoNombre', ''),
                    'cantidad': cant,
                    'precio_unitario': pu,
                    'subtotal': linea_subt,
                    'costo_estimado': costo_est,
                    'opcionales': l.get('opcionales', []),
                    'notas': l.get('notas', ''),
                    'foto': l.get('foto'),
                })

            subtotal -= _aplicar_decorativos(lineas_info, lineas_instancias)
            descuento = Decimal(str(self.request.data.get('descuento', 0)))
            validar_descuento_documento(lineas_info, descuento)
            descuento_porcentaje = ((descuento / subtotal) * Decimal('100')).quantize(Decimal('0.01')) if subtotal > 0 else Decimal('0.00')
            total = max(Decimal('0.00'), subtotal - descuento)

            cotizacion = serializer.save(
                numero=numero,
                asesor=user,
                asesor_nombre=asesor_nombre,
                cliente_nombre=cliente_nombre,
                fecha_vencimiento=fecha_vencimiento,
                subtotal=subtotal,
                descuento=descuento,
                descuento_porcentaje=descuento_porcentaje,
                total=total,
                version=1,
            )

            for li in lineas_instancias:
                LineaCotizacion.objects.create(
                    cotizacion=cotizacion,
                    **li
                )

            auditar(user, 'CREAR_COTIZACION', cotizacion, {'numero': numero, 'total': str(total)})

    def update(self, request, *args, **kwargs):
        cotizacion = self.get_object()
        # Invariante: una cotización aceptada o convertida queda congelada
        if cotizacion.estado in [Cotizacion.ESTADO_ACEPTADA, Cotizacion.ESTADO_CONVERTIDA]:
            return Response(
                {"detail": "Una cotización aceptada o convertida no puede ser modificada. Duplica la cotización si necesitas una nueva versión."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Control de concurrencia optimista
        version_enviada = request.data.get('version')
        if version_enviada is not None and int(version_enviada) != cotizacion.version:
            return Response(
                {"detail": "La cotización fue modificada por otro usuario o en otra sesión. Recarga para ver los cambios recientes."},
                status=status.HTTP_409_CONFLICT
            )

        with transaction.atomic():
            cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
            descuento = Decimal(str(request.data.get('descuento', cotizacion.descuento)))
            if 'lineas' in request.data:
                lineas_data = request.data.get('lineas', [])
                if not lineas_data:
                    return Response({"lineas": "Una cotización requiere al menos un producto o línea."}, status=400)
                cotizacion.lineas.all().delete()
                subtotal = Decimal('0.00')
                lineas_instancias = []
                variante_ids = [l.get('variante') or l.get('variante_id') for l in lineas_data if l.get('variante') or l.get('variante_id')]
                variantes_map = {v.id: v for v in VarianteProducto.objects.filter(id__in=variante_ids).select_related('linea').prefetch_related('cargos__especial', 'precios', *PREFETCH_JUEGOS)}
                grupo_ids = [l.get('grupo_tela') or l.get('grupoId') for l in lineas_data if l.get('grupo_tela') or l.get('grupoId')]
                grupos_map = {g.id: g for g in GrupoTela.objects.filter(id__in=grupo_ids)}

                lineas_info = []
                for l in lineas_data:
                    cant = max(1, int(l.get('cantidad', 1)))
                    pu = Decimal(str(l.get('precio_unitario', 0)))
                    linea_subt = (pu * cant).quantize(Decimal('0.01'))
                    subtotal += linea_subt

                    v_id = l.get('variante') or l.get('variante_id')
                    v_obj = variantes_map.get(int(v_id)) if v_id else None
                    g_id = l.get('grupo_tela') or l.get('grupoId')
                    g_obj = grupos_map.get(int(g_id)) if g_id else None

                    costo_est = costo_lista(v_obj, g_obj, l.get('opcionales', [])) if v_obj else None

                    lineas_info.append({
                        'subtotal': linea_subt,
                        'variante_obj': v_obj,
                        'grupo_obj': g_obj,
                        'cantidad': cant,
                    })
                    lineas_instancias.append({
                        'variante_id': v_obj.id if v_obj else None,
                        'linea_nombre': l.get('linea_nombre') or l.get('lineaNombre', 'Línea'),
                        'variante_nombre': l.get('variante_nombre') or l.get('varianteNombre', 'Producto'),
                        'categoria_nombre': l.get('categoria_nombre') or l.get('categoriaNombre', ''),
                        'grupo_tela_id': g_obj.id if g_obj else None,
                        'grupo_nombre': l.get('grupo_nombre') or l.get('grupoNombre', ''),
                        'cantidad': cant,
                        'precio_unitario': pu,
                        'subtotal': linea_subt,
                        'costo_estimado': costo_est,
                        'opcionales': l.get('opcionales', []),
                        'notas': l.get('notas', ''),
                        'foto': l.get('foto'),
                    })

                subtotal -= _aplicar_decorativos(lineas_info, lineas_instancias)
                validar_descuento_documento(lineas_info, descuento)
                for li in lineas_instancias:
                    LineaCotizacion.objects.create(
                        cotizacion=cotizacion,
                        **li
                    )
                self._nuevo_subtotal = subtotal
                self._nuevo_descuento = descuento
                self._nuevo_descuento_porcentaje = ((descuento / subtotal) * Decimal('100')).quantize(Decimal('0.01')) if subtotal > 0 else Decimal('0.00')
                self._nuevo_total = max(Decimal('0.00'), subtotal - descuento)
            elif 'descuento' in request.data:
                lineas_existentes = cotizacion.lineas.select_related('variante').all()
                lineas_info = [{'subtotal': lc.subtotal, 'variante_obj': lc.variante} for lc in lineas_existentes]
                validar_descuento_documento(lineas_info, descuento)
                self._nuevo_subtotal = cotizacion.subtotal
                self._nuevo_descuento = descuento
                self._nuevo_descuento_porcentaje = ((descuento / cotizacion.subtotal) * Decimal('100')).quantize(Decimal('0.01')) if cotizacion.subtotal > 0 else Decimal('0.00')
                self._nuevo_total = max(Decimal('0.00'), cotizacion.subtotal - descuento)

            response = super().update(request, *args, **kwargs)
            cotizacion.refresh_from_db()
            auditar(request.user, 'EDITAR_COTIZACION', cotizacion, {'version': cotizacion.version})
            return response

    def perform_update(self, serializer):
        cotizacion = serializer.instance
        extra_fields = {'version': cotizacion.version + 1}
        if hasattr(self, '_nuevo_subtotal'):
            extra_fields['subtotal'] = self._nuevo_subtotal
            extra_fields['descuento'] = self._nuevo_descuento
            extra_fields['descuento_porcentaje'] = self._nuevo_descuento_porcentaje
            extra_fields['total'] = self._nuevo_total
        serializer.save(**extra_fields)

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    def cambiar_estado(self, request, pk=None):
        cotizacion = self.get_object()
        nuevo_estado = request.data.get('estado')
        if nuevo_estado not in dict(Cotizacion.ESTADO_CHOICES):
            return Response({"error": f"Estado '{nuevo_estado}' no válido."}, status=400)

        if cotizacion.estado == Cotizacion.ESTADO_CONVERTIDA:
            return Response({"error": "Una cotización ya convertida a venta no puede cambiar de estado."}, status=400)

        cotizacion.estado = nuevo_estado
        cotizacion.save(update_fields=['estado', 'updated_at'])
        auditar(request.user, 'CAMBIAR_ESTADO_COTIZACION', cotizacion, {'nuevo_estado': nuevo_estado})
        return Response({"message": f"Estado cambiado a {nuevo_estado}.", "estado": nuevo_estado})

    @action(detail=True, methods=['post'], url_path='convertir-a-venta')
    @transaction.atomic
    def convertir_a_venta(self, request, pk=None):
        """Convierte una cotización aceptada a venta en una operación autorizada,
        atómica e idempotente (P09-04 / F01, F02).
        Prorratea el descuento del documento entre las líneas para que cada línea tenga
        un subtotal neto y margen explicables, garantizando sum(subtotal) == venta.valor_total."""
        if not tiene_permiso_codigo(request, 'CREAR_VENTA'):
            return Response({"error": "No tienes permiso para crear ventas."}, status=status.HTTP_403_FORBIDDEN)

        cotizacion = Cotizacion.objects.select_for_update().prefetch_related('lineas').get(pk=pk)

        # Idempotencia: si ya fue convertida previamente, devuelve la venta asociada
        if cotizacion.estado == Cotizacion.ESTADO_CONVERTIDA and cotizacion.venta_asociada_id:
            return Response({
                "message": "La cotización ya fue convertida previamente a venta.",
                "venta_id": cotizacion.venta_asociada_id,
                "cliente_id": cotizacion.cliente_id,
                "numero_cotizacion": cotizacion.numero,
            }, status=status.HTTP_200_OK)

        if cotizacion.estado not in [Cotizacion.ESTADO_EMITIDA, Cotizacion.ESTADO_ACEPTADA]:
            return Response({
                "error": f"No se puede convertir una cotización en estado '{cotizacion.get_estado_display()}'. Debe estar emitida o aceptada."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Resolver cliente
        cliente = cotizacion.cliente
        cliente_data = request.data.get('cliente')
        cliente_id = request.data.get('cliente_id')
        if cliente_id:
            cliente = Cliente.objects.filter(pk=cliente_id).first()
        elif cliente_data:
            if isinstance(cliente_data, dict) and cliente_data.get('id'):
                cliente = Cliente.objects.filter(pk=cliente_data['id']).first()
            if not cliente:
                c_ser = ClienteSerializer(data=cliente_data)
                c_ser.is_valid(raise_exception=True)
                cliente = c_ser.save()
        elif not cliente and cotizacion.cliente_documento:
            cliente = Cliente.objects.filter(cedula=cotizacion.cliente_documento).first()

        if not cliente:
            return Response({
                "error": "Debes especificar o seleccionar un cliente para convertir la cotización a venta."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Determinar ID de venta
        venta_id = request.data.get('venta_id')
        if venta_id:
            if Venta.objects.filter(id=venta_id).exists():
                return Response({"error": "El ID de la venta ya existe."}, status=400)
        else:
            max_v_id = Venta.objects.aggregate(m=models.Max('id'))['m'] or 2000
            venta_id = siguiente_consecutivo('venta', 2001, max_v_id)

        fecha_entrega = request.data.get('fecha_entrega') or (timezone.localdate() + datetime.timedelta(days=15))
        sede = request.data.get('sede', 'Lottus 1')

        # Crear Venta
        venta = Venta.objects.create(
            id=venta_id,
            cliente=cliente,
            vendedor=cotizacion.asesor,
            valor_total=cotizacion.total,
            abono=Decimal('0.00'),
            saldo=cotizacion.total,
            fecha_venta=timezone.localdate(),
            fecha_entrega=fecha_entrega,
            sede=sede,
            estado='pendiente',
        )

        # Crear LineaVenta para cada LineaCotizacion prorrateando el descuento del documento
        lineas = list(cotizacion.lineas.all())
        num_lineas = len(lineas)
        descuento_restante = cotizacion.descuento

        for idx, lc in enumerate(lineas):
            if cotizacion.subtotal > Decimal('0.00') and cotizacion.descuento > Decimal('0.00'):
                if idx == num_lineas - 1:
                    desc_linea = descuento_restante
                else:
                    desc_linea = ((cotizacion.descuento * lc.subtotal) / cotizacion.subtotal).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
                    descuento_restante -= desc_linea
            else:
                desc_linea = Decimal('0.00')

            subt_linea = max(Decimal('0.00'), lc.subtotal - desc_linea)

            LineaVenta.objects.create(
                venta=venta,
                variante=lc.variante,
                producto_nombre=lc.linea_nombre,
                variante_nombre=lc.variante_nombre,
                categoria_nombre=lc.categoria_nombre,
                grupo_tela=lc.grupo_nombre,
                especificaciones=lc.notas,
                cantidad=lc.cantidad,
                precio_unitario=lc.precio_unitario,
                descuento=desc_linea,
                subtotal=subt_linea,
                costo_estimado=lc.costo_estimado,
                fecha_compromiso=venta.fecha_entrega,
                opcionales=lc.opcionales,
                notas=lc.notas,
            )

        # Actualizar Cotizacion
        cotizacion.estado = Cotizacion.ESTADO_CONVERTIDA
        cotizacion.venta_asociada = venta
        cotizacion.cliente = cliente
        cotizacion.fecha_conversion = timezone.now()
        cotizacion.save(update_fields=['estado', 'venta_asociada', 'cliente', 'fecha_conversion', 'updated_at'])

        auditar(request.user, 'CONVERTIR_COTIZACION', cotizacion, {
            'venta_id': venta.id,
            'cliente_id': cliente.id,
            'total': str(cotizacion.total),
        })

        return Response({
            "message": "Cotización convertida a venta exitosamente.",
            "venta_id": venta.id,
            "cliente_id": cliente.id,
            "numero_cotizacion": cotizacion.numero,
        }, status=status.HTTP_201_CREATED)
