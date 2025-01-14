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
    Endpoint para listar las órdenes de pedido con datos personalizados.
    """
    query = """
    SELECT 
        o.id AS id_orden, 
        p.nombre_empresa AS proveedor, 
        CONCAT(u.first_name, ' ', u.last_name) AS vendedor, 
        o.fecha_creacion, 
        o.fecha_esperada, 
        o.estado, 
        o.notas AS nota 
    FROM 
        ordenes_ordenpedido o 
    JOIN 
        ordenes_proveedor p ON o.proveedor_id = p.id 
    JOIN 
        auth_user u ON o.usuario_id = u.id 
    ORDER BY 
        o.fecha_creacion DESC 
    LIMIT 25;
    """
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
    
    # Formatear los resultados como lista de diccionarios
    results = [dict(zip(columns, row)) for row in rows]

    return Response(results)

def home(request):
    return HttpResponse("<h1>Bienvenido a LottusPedidos</h1><p>Por favor, dirígete a /api/login/ para iniciar sesión.</p>")
