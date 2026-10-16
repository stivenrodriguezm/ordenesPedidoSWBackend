from django.db.models import Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import calidad_clientes as dominio
from .models import CorreccionCliente
from .permissions import check_feature_permission
from .servicios import idempotente


class CalidadPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

class CorreccionEntrada(serializers.Serializer):
    version = serializers.CharField(max_length=1000)
    campos = serializers.ListField(child=serializers.ChoiceField(choices=dominio.EDITABLES), allow_empty=False)


class ComparacionEntrada(serializers.Serializer):
    origen = serializers.IntegerField(min_value=1, max_value=2147483647)
    destino = serializers.IntegerField(min_value=1, max_value=2147483647)


class HistorialCalidadSerializer(serializers.ModelSerializer):
    responsable = serializers.CharField(source='usuario.username', read_only=True)
    class Meta:
        model = CorreccionCliente
        fields = ['id', 'cliente', 'fecha', 'responsable', 'cambios']
        read_only_fields = fields


class CalidadClientesViewSet(viewsets.GenericViewSet):
    lookup_value_regex = r'[0-9]+'
    pagination_class = CalidadPagination

    def get_permissions(self):
        permisos = [IsAuthenticated(), check_feature_permission('VER_CLIENTES')(), check_feature_permission('VER_CALIDAD_CLIENTES')()]
        if self.action == 'normalizar':
            permisos.extend([check_feature_permission('EDITAR_CLIENTE')(), check_feature_permission('NORMALIZAR_CLIENTES')()])
        return permisos

    def get_queryset(self):
        return dominio.clientes_visibles(self.request)

    def busqueda(self):
        return serializers.CharField(max_length=100, allow_blank=True).run_validation(self.request.query_params.get('buscar', ''))

    def list(self, request):
        qs = self.get_queryset()
        buscar = self.busqueda()
        if buscar:
            qs = qs.filter(Q(nombre__icontains=buscar) | Q(cedula__icontains=buscar) | Q(correo__icontains=buscar)
                           | Q(telefono1__icontains=buscar) | Q(telefono2__icontains=buscar))
        if self.request.query_params.get('con_correcciones') in ('1', 'true'):
            # Solo las fichas con algo por corregir: listar las 900+ sin cambios no ayuda a revisar.
            vistas = [v for v in (dominio.vista_cliente(c) for c in qs) if v['cambios']]
            return self.get_paginated_response(self.paginate_queryset(vistas))
        return self.get_paginated_response([dominio.vista_cliente(c) for c in self.paginate_queryset(qs)])

    def retrieve(self, request, pk=None):
        return Response(dominio.vista_cliente(self.get_object()))

    @action(detail=False, methods=['get'])
    def candidatos(self, request):
        grupos, revisados = dominio.buscar_candidatos(request, self.busqueda())
        data = self.get_paginated_response(self.paginate_queryset(grupos)).data
        data['clientes_revisados'] = revisados
        return Response(data)

    @action(detail=False, methods=['get'])
    def comparar(self, request):
        entrada = ComparacionEntrada(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        return Response(dominio.comparar(request, **entrada.validated_data))

    @action(detail=True, methods=['post'])
    def normalizar(self, request, pk=None):
        # Revalidar alcance incluso antes de devolver una respuesta idempotente.
        self.get_object()
        return self._normalizar(request, pk)

    @idempotente('cliente.normalizar')
    def _normalizar(self, request, pk):
        entrada = CorreccionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        return Response(dominio.corregir(request, pk, **entrada.validated_data))

    @action(detail=True, methods=['get'])
    def historial(self, request, pk=None):
        cliente = self.get_object()
        qs = cliente.correcciones_formato.select_related('usuario')
        return self.get_paginated_response(HistorialCalidadSerializer(self.paginate_queryset(qs), many=True).data)
