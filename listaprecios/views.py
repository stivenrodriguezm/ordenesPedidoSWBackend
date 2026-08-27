import datetime
import logging
import os
import uuid

from django.db.models import Q, Prefetch
from django.db.models.deletion import ProtectedError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ordenes.permissions import check_feature_permission
from paginaweb.sirv import upload_to_sirv, SirvUploadError

from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante,
)
from .serializers import (
    CategoriaListaSerializer, CategoriaListaPublicSerializer, GrupoTelaSerializer, MultiplicadorSerializer,
    LineaProductoSerializer, VarianteProductoSerializer,
    CargoVarianteSerializer, PrecioVarianteSerializer, LineaCatalogoSerializer,
)
from .services import (
    impacto_categoria, impacto_multiplicador, impacto_grupo_tela, obtener_grupos_tela, calcular_precio,
    opcionales_de_variante, obtener_multiplicador_general, establecer_multiplicador_general,
    asignar_multiplicador_masivo,
)

logger = logging.getLogger(__name__)


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


class CategoriaListaViewSet(viewsets.ModelViewSet):
    """Categorías = tipo de producto — solo etiqueta, no define ningún
    precio (el precio por grupo es global, ver GrupoTela). Tampoco tienen
    multiplicador — eso vive en Multiplicador, completamente aparte."""
    queryset = CategoriaLista.objects.all()
    serializer_class = CategoriaListaSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]

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
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]

    def perform_create(self, serializer):
        instance = serializer.save()
        if instance.es_general:
            establecer_multiplicador_general(instance)
        elif not Multiplicador.objects.filter(es_general=True).exclude(pk=instance.pk).exists():
            # El primer multiplicador que se crea queda como general por
            # defecto — nunca puede quedar el catálogo sin ninguno general.
            establecer_multiplicador_general(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.es_general:
            establecer_multiplicador_general(instance)

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


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_LISTA_PRECIOS')])
def categorias_publicas(request):
    """GET /api/listaprecios/categorias-publicas/ — nombre/slug/orden solo,
    para los chips de filtro del catálogo de vendedor. No expone margen."""
    qs = CategoriaLista.objects.filter(activo=True)
    return Response(CategoriaListaPublicSerializer(qs, many=True).data)


class GrupoTelaViewSet(viewsets.ModelViewSet):
    queryset = GrupoTela.objects.all()
    serializer_class = GrupoTelaSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_LISTA_PRECIOS')()]

    @action(detail=True, methods=['get'])
    def impacto(self, request, pk=None):
        grupo = self.get_object()
        return Response(impacto_grupo_tela(grupo))


class LineaProductoViewSet(viewsets.ModelViewSet):
    """Vista de administración (incluye costos anidados de las variantes)."""
    queryset = LineaProducto.objects.prefetch_related(
        Prefetch('variantes', queryset=VarianteProducto.objects.select_related('categoria', 'multiplicador')),
        'variantes__cargos', 'variantes__precios', 'variantes__precios__grupo',
    ).all()
    serializer_class = LineaProductoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['activo']
    # Busca por nombre de la línea/colección (ej. "Detroit") o por nombre de
    # cualquiera de sus variantes (ej. "Sofá 3p.") — cualquiera de las dos
    # formas en que el admin suele buscar un producto.
    search_fields = ['nombre', 'variantes__nombre']

    def get_queryset(self):
        qs = self.queryset
        categoria = self.request.query_params.get('categoria')
        if categoria:
            qs = qs.filter(variantes__categoria=categoria)
        # distinct() siempre: tanto el filtro por categoría como la búsqueda
        # por variantes__nombre atraviesan una relación a-muchos y pueden
        # duplicar filas de LineaProducto sin esto.
        return qs.distinct()

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]

    def get_serializer_context(self):
        # Precarga los grupos de tela y el multiplicador general en un solo
        # query cada uno — evita que cada variante/precio anidado dispare
        # su propia consulta (ver services.calcular_precio).
        context = super().get_serializer_context()
        context.update(_precios_context())
        return context

    def perform_create(self, serializer):
        data = self.request.data
        nombre = data.get('nombre', 'Línea')
        slug = data.get('slug')
        if not slug:
            from django.utils.text import slugify
            slug = slugify(nombre)
            base_slug = slug
            count = 1
            while LineaProducto.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{count}"
                count += 1
        serializer.save(slug=slug)


class VarianteProductoViewSet(viewsets.ModelViewSet):
    queryset = VarianteProducto.objects.select_related('linea', 'categoria', 'multiplicador').prefetch_related('cargos', 'precios').all()
    serializer_class = VarianteProductoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['linea', 'categoria', 'multiplicador']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(_precios_context())
        return context

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
        return Response({'ok': True, 'actualizadas': actualizadas})


class CargoVarianteViewSet(viewsets.ModelViewSet):
    queryset = CargoVariante.objects.all()
    serializer_class = CargoVarianteSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['variante']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]


class PrecioVarianteViewSet(viewsets.ModelViewSet):
    queryset = PrecioVariante.objects.select_related('grupo', 'variante').all()
    serializer_class = PrecioVarianteSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['variante']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_LISTA_PRECIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_LISTA_PRECIOS')()]

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
        'variantes__precios', 'variantes__precios__grupo', 'variantes__cargos',
    )

    categoria_slug = request.GET.get('categoria')
    q = request.GET.get('q')

    if categoria_slug:
        qs = qs.filter(variantes__categoria__slug=categoria_slug).distinct()
    if q:
        needle = q.strip()
        qs = qs.filter(
            Q(nombre__icontains=needle) | Q(notas__icontains=needle) | Q(variantes__notas__icontains=needle)
        ).distinct()

    context = _precios_context()
    serializer = LineaCatalogoSerializer(qs, many=True, context=context)
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
        .prefetch_related('cargos', 'precios').filter(id=variante_id).first()
    )
    if variante is None:
        return Response({'error': 'Variante no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    grupo_id = request.GET.get('grupo')
    grupo = None
    if grupo_id:
        grupo = GrupoTela.objects.filter(id=grupo_id).first()
        if grupo is None:
            return Response({'error': 'Grupo de tela no encontrado'}, status=status.HTTP_400_BAD_REQUEST)

    opcionales_raw = request.GET.get('opcionales', '')
    try:
        opcionales_ids = {int(x) for x in opcionales_raw.split(',') if x.strip()}
    except ValueError:
        return Response({'error': 'Parámetro opcionales inválido'}, status=status.HTTP_400_BAD_REQUEST)

    precio = calcular_precio(variante, grupo, opcionales_ids=opcionales_ids)
    incluidos = [o for o in opcionales_de_variante(variante) if o['id'] in opcionales_ids]
    return Response({'precio': precio, 'opcionales_incluidos': incluidos})


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('EDITAR_LISTA_PRECIOS')])
def upload_foto(request):
    """POST /api/listaprecios/upload-foto/ — sube foto(s) de una línea a
    Sirv, mismo flujo que paginaweb.admin_upload_image."""
    files = request.FILES.getlist('images') or request.FILES.getlist('file')
    if not files:
        return Response({"error": "No se enviaron archivos"}, status=status.HTTP_400_BAD_REQUEST)

    uploaded_urls = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        content_type = f.content_type
        file_bytes = f.read()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif']:
            ext = '.jpg'
        filename = f"listaprecios/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        try:
            url = upload_to_sirv(file_bytes, filename, content_type)
        except SirvUploadError:
            logger.exception("Error subiendo foto de lista de precios a Sirv")
            return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)
        uploaded_urls.append(url)

    return Response({"ok": True, "urls": uploaded_urls, "url": uploaded_urls[0] if uploaded_urls else None})
