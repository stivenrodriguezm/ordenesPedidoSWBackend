from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response  # Importación necesaria
from django.http import HttpResponse, JsonResponse
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido, CustomUser
from .serializers import ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer, DetallePedidoSerializer
from .permissions import IsAdmin, IsVendedor
from django.db import connection
from django.db.models import Q
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_vendedores(request):
    """
    Devuelve una lista de usuarios con rol de 'VENDEDOR' y que estén activos
    """
    vendedores = CustomUser.objects.filter(is_active=True, role=CustomUser.VENDEDOR)
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
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']

    def get_queryset(self):
        if self.request.user.is_staff:
            return OrdenPedido.objects.all()
        return OrdenPedido.objects.filter(usuario=self.request.user)

    def get_serializer_context(self):
        return {'request': self.request}

    def update(self, request, *args, **kwargs):
        print("Datos recibidos:", request.data)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            print("Errores de validación:", e.detail)
            return Response({"error": "Datos inválidos", "detalles": e.detail}, status=400)

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
            "role": user.role,  # Indica si es administrador
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_pedidos(request):
    """
    Endpoint para listar órdenes de pedido con filtros dinámicos.
    """
    usuario = request.user
    estado = request.GET.get('estado')
    id_proveedor = request.GET.get('id_proveedor')
    id_vendedor = request.GET.get('id_vendedor')  # ✅ Nuevo filtro

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
        ordenes_customuser u ON o.usuario_id = u.id
    """

    # Construcción de filtros dinámicos
    filters = []
    params = []

    # 🚀 Restricción para VENDEDORES: solo pueden ver sus propios pedidos
    if usuario.role == "VENDEDOR":
        filters.append("o.usuario_id = %s")
        params.append(usuario.id)

    # ✅ Filtrar por ID de vendedor (si lo solicita un administrador)
    if id_vendedor and id_vendedor.isdigit():
        filters.append("o.usuario_id = %s")
        params.append(int(id_vendedor))

    # ✅ Filtrar por estado
    if estado and estado.strip():
        filters.append("o.estado = %s")
        params.append(estado.strip())

    # ✅ Filtrar por proveedor
    if id_proveedor and id_proveedor.isdigit():
        filters.append("o.proveedor_id = %s")
        params.append(int(id_proveedor))

    # Agregar filtros a la consulta
    if filters:
        query += " WHERE " + " AND ".join(filters)

    # Ordenar por ID descendente
    query += " ORDER BY o.id DESC;"

    # 🔍 Depuración: Ver la consulta generada y los parámetros
    # print("QUERY FINAL:", query)
    # print("PARAMS:", params)

    # Ejecutar la consulta
    with connection.cursor() as cursor:
        try:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    # Formatear los resultados
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
