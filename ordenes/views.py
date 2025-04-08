from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.http import HttpResponse, JsonResponse
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido, CustomUser
from .serializers import ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer, DetallePedidoSerializer
from .permissions import IsAdmin, IsVendedor
from django.db import connection
from django.db.models import Q
from rest_framework import status
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_vendedores(request):
    """Devuelve una lista de usuarios con rol de 'VENDEDOR' y que estén activos"""
    vendedores = CustomUser.objects.filter(is_active=True)
    data = [{"id": v.id, "first_name": v.first_name} for v in vendedores]
    return Response(data)

class ReferenciaViewSet(viewsets.ModelViewSet):
    queryset = Referencia.objects.all()
    serializer_class = ReferenciaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        proveedor_id = self.request.query_params.get('proveedor')
        if proveedor_id:
            queryset = queryset.filter(proveedor_id=proveedor_id)
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
        # Permitir que ADMINISTRADOR y AUXILIAR vean y modifiquen todos los pedidos
        if self.request.user.role in ["ADMINISTRADOR", "AUXILIAR"]:
            return OrdenPedido.objects.all()
        # Los VENDEDORES solo pueden ver y modificar sus propios pedidos
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
        return Response({
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
        })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_contrasena(request):
    user = request.user
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not user.check_password(old_password):
        return Response({"error": "La contraseña actual es incorrecta."}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({"message": "Contraseña actualizada correctamente."}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_pedidos(request):
    """Endpoint para listar órdenes de pedido con filtros dinámicos."""
    usuario = request.user
    estado = request.GET.get('estado')
    id_proveedor = request.GET.get('id_proveedor')
    id_vendedor = request.GET.get('id_vendedor')
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
        o.orden_venta,
        o.tela  -- Incluir el campo 'tela'
    FROM 
        ordenes_ordenpedido o 
    JOIN 
        ordenes_proveedor p ON o.proveedor_id = p.id 
    JOIN 
        ordenes_customuser u ON o.usuario_id = u.id
    """
    filters = []
    params = []
    if usuario.role == "VENDEDOR":
        filters.append("o.usuario_id = %s")
        params.append(usuario.id)
    if id_vendedor and id_vendedor.isdigit():
        filters.append("o.usuario_id = %s")
        params.append(int(id_vendedor))
    if estado and estado.strip():
        filters.append("o.estado = %s")
        params.append(estado.strip())
    if id_proveedor and id_proveedor.isdigit():
        filters.append("o.proveedor_id = %s")
        params.append(int(id_proveedor))
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY o.id DESC;"
    with connection.cursor() as cursor:
        try:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
        except Exception as e:
            return Response({"error": str(e)}, status=400)
    results = [dict(zip(columns, row)) for row in rows]
    return Response(results)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalles_pedido(request, orden_id):
    """Devuelve los detalles de productos de una orden de pedido específica."""
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