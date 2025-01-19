from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response  # Importación necesaria
from django.http import HttpResponse, JsonResponse
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido
from .serializers import ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer, DetallePedidoSerializer
from .permissions import IsAdmin, IsVendedor
from django.db import connection
from django.db.models import Q
from django.contrib.auth.models import User

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_vendedores(request):
    """
    Devuelve una lista de usuarios activos
    """
    vendedores = User.objects.filter(is_active=True)  # Filtra solo los usuarios activos
    data = [{"id": v.id, "first_name": v.first_name} for v in vendedores]
    return Response(data)

class ReferenciaViewSet(viewsets.ModelViewSet):
    queryset = Referencia.objects.all()
    serializer_class = ReferenciaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        proveedor_id = self.request.query_params.get('proveedor')  # Obtener el proveedor del query param
        if proveedor_id:
            queryset = queryset.filter(proveedor_id=proveedor_id)  # Filtrar referencias por proveedor
        return queryset

class ProveedorViewSet(viewsets.ModelViewSet):
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    permission_classes = [IsAuthenticated]

class OrdenPedidoViewSet(viewsets.ModelViewSet):
    queryset = OrdenPedido.objects.all()
    serializer_class = OrdenPedidoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return OrdenPedido.objects.all()
        return OrdenPedido.objects.filter(usuario=self.request.user)

    def get_serializer_context(self):
        # Agregar el contexto del request al serializer
        return {'request': self.request}

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class DetallePedidoViewSet(viewsets.ModelViewSet):
    queryset = DetallePedido.objects.all()
    serializer_class = DetallePedidoSerializer
    permission_classes = [IsAuthenticated]

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({  # Aquí se usa Response
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,  # Nombre del usuario
            "last_name": user.last_name,    # Apellido del usuario
            "is_staff": user.is_staff,  # Indica si es administrador
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_pedidos(request):
    """
    Endpoint para listar las órdenes de pedido con datos personalizados y filtros.
    """
    usuario = request.user
    estado = request.GET.get('estado', None)
    id_vendedor = request.GET.get('id_vendedor', None)
    id_proveedor = request.GET.get('id_proveedor', None)

    # Consulta base
    query = """
    SELECT 
        o.id AS id_orden, 
        p.nombre_empresa AS proveedor, 
        u.first_name AS vendedor, 
        o.fecha_creacion, 
        o.fecha_esperada, 
        o.estado, 
        o.notas AS nota,
        o.costo,
        o.orden_venta
    FROM 
        ordenes_ordenpedido o 
    JOIN 
        ordenes_proveedor p ON o.proveedor_id = p.id 
    JOIN 
        auth_user u ON o.usuario_id = u.id
    """

    # Construir filtros dinámicamente
    filters = []

    # Los vendedores solo ven sus pedidos (excepto administradores)
    if not usuario.is_staff:
        filters.append("o.usuario_id = %s")

    # Filtros adicionales
    if estado:
        filters.append("o.estado = %s")
    if id_vendedor:
        filters.append("o.usuario_id = %s")
    if id_proveedor:
        filters.append("o.proveedor_id = %s")

    # Agregar filtros a la consulta
    if filters:
        query += " WHERE " + " AND ".join(filters)

    # Ordenar por ID descendente
    query += " ORDER BY o.id DESC;"

    # Preparar parámetros para la consulta
    params = []
    if not usuario.is_staff:
        params.append(usuario.id)
    if estado:
        params.append(estado)
    if id_vendedor:
        params.append(id_vendedor)
    if id_proveedor:
        params.append(id_proveedor)

    # Ejecutar la consulta
    with connection.cursor() as cursor:
        try:
            cursor.execute(query, params)  # Pasar parámetros para evitar inyección SQL
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    # Formatear los resultados como lista de diccionarios
    results = [dict(zip(columns, row)) for row in rows]
    return Response(results)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalles_pedido(request, orden_id):
    """
    Devuelve los detalles de productos de una orden de pedido específica.
    """
    try:
        detalles = DetallePedido.objects.filter(orden_id=orden_id).select_related('referencia')
        data = [
            {
                "cantidad": detalle.cantidad,
                "especificaciones": detalle.especificaciones,
                "referencia": detalle.referencia.nombre if detalle.referencia else "Sin referencia"
            }
            for detalle in detalles
        ]
        return Response(data, status=200)
    except DetallePedido.DoesNotExist:
        return Response({"error": "No se encontraron detalles para esta orden."}, status=404)



def home(request):
    return HttpResponse("<h1>Bienvenido a LottusPedidos</h1><p>Por favor, dirígete a /api/login/ para iniciar sesión.</p>")
