from rest_framework import serializers
from .models import (
    Referencia, Proveedor, OrdenPedido, DetallePedido, Cliente, Venta, 
    ObservacionVenta, ObservacionCliente, Remision, ReciboCaja, Caja, ComprobanteEgreso
)
from django.db import transaction

class ReferenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referencia
        fields = '__all__'

class ProveedorSerializer(serializers.ModelSerializer):
    referencias = ReferenciaSerializer(many=True, read_only=True)
    class Meta:
        model = Proveedor
        fields = '__all__'

class DetallePedidoSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.CharField(source='referencia.nombre', read_only=True)
    class Meta:
        model = DetallePedido
        fields = ['cantidad', 'especificaciones', 'referencia', 'referencia_nombre']
        extra_kwargs = {
            'referencia': {'write_only': True}
        }

class OrdenPedidoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.SerializerMethodField()
    vendedor = serializers.SerializerMethodField()
    detalles = DetallePedidoSerializer(many=True, write_only=True, required=False)
    fecha_pedido = serializers.DateField(source='fecha_creacion', read_only=True) # Mapea fecha_pedido a fecha_creacion

    class Meta:
        model = OrdenPedido
        fields = [
            'id', 'proveedor', 'proveedor_nombre', 'fecha_pedido', 'fecha_esperada', 
            'estado', 'observacion', 'tela', 'venta', 'costo',
            'vendedor', 'detalles', 'orden_venta'
        ]
        extra_kwargs = {
            'proveedor': {'write_only': True, 'queryset': Proveedor.objects.all()},
            'venta': {'required': False, 'allow_null': True} 
        }

    def get_proveedor_nombre(self, obj):
        return obj.proveedor.nombre_empresa if obj.proveedor else None

    def get_vendedor(self, obj):
        return obj.usuario.first_name if obj.usuario else None

    @transaction.atomic
    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles', [])
        orden = OrdenPedido.objects.create(**validated_data)
        for detalle_data in detalles_data:
            DetallePedido.objects.create(orden=orden, **detalle_data)
        return orden

class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'

class VentaSerializer(serializers.ModelSerializer):
    saldo = serializers.DecimalField(max_digits=10, decimal_places=2) 
    abono = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)

    class Meta:
        model = Venta
        fields = [
            'id', 'fecha_venta', 'vendedor', 'vendedor_nombre', 'cliente', 'cliente_nombre', 'valor_total', 
            'abono', 'saldo', 'fecha_entrega', 'estado', 'estado_pedidos'
        ]
        extra_kwargs = {
            'vendedor': {'write_only': True},
            'cliente': {'write_only': True}
        }
        
    def to_representation(self, instance):
        return {
            'id_venta': instance.id,
            'fecha_venta': instance.fecha_venta,
            'vendedor': instance.vendedor.first_name if instance.vendedor else None,
            'cliente': instance.cliente.nombre if instance.cliente else None,
            'abono': f"{int(instance.abono) if instance.abono is not None else 0}",
            'saldo': f"{int(instance.saldo) if instance.saldo is not None else 0}",
            'valor': f"{int(instance.valor_total) if instance.valor_total is not None else 0}",
            'fecha_entrega': instance.fecha_entrega,
            'pedido': 'Finalizado' if instance.estado_pedidos else 'Pendiente',
            'estado': instance.estado,
        }

class ObservacionVentaSerializer(serializers.ModelSerializer):
    autor = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True, required=False)
    autor_username = serializers.SerializerMethodField()

    class Meta:
        model = ObservacionVenta
        fields = ['id', 'texto', 'fecha', 'autor', 'autor_username', 'venta']
        read_only_fields = ['venta']

    def get_autor_username(self, obj):
        try:
            return obj.autor.username if obj.autor else None
        except Exception:
            return "Usuario Desconocido"

class ObservacionClienteSerializer(serializers.ModelSerializer):
    autor = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True, required=False)
    autor_username = serializers.SerializerMethodField()

    class Meta:
        model = ObservacionCliente
        fields = ['id', 'texto', 'fecha', 'autor', 'autor_username', 'cliente']
        read_only_fields = ['cliente']

    def get_autor_username(self, obj):
        try:
            return obj.autor.username if obj.autor else None
        except Exception:
            return "Usuario Desconocido"

class RemisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Remision
        fields = '__all__'

class ReciboCajaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReciboCaja
        fields = '__all__'

from django.db import transaction

class CajaSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.first_name', read_only=True)

    class Meta:
        model = Caja
        fields = ['id', 'fecha_hora', 'concepto', 'tipo', 'valor', 'total_acumulado', 'usuario', 'usuario_nombre']
        read_only_fields = ['id', 'fecha_hora', 'total_acumulado', 'usuario', 'usuario_nombre']

    def create(self, validated_data):
        validated_data['usuario'] = self.context['request'].user
        valor = validated_data.get('valor')
        tipo = validated_data.get('tipo')

        with transaction.atomic():
            # Obtener el último movimiento para calcular el nuevo total acumulado
            last_movement = Caja.objects.order_by('-fecha_hora').first()
            last_total = last_movement.total_acumulado if last_movement else 0

            if tipo == 'ingreso':
                new_total = last_total + valor
            else:  # egreso
                new_total = last_total - valor
            
            validated_data['total_acumulado'] = new_total
            
            return super().create(validated_data)

class ComprobanteEgresoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source='proveedor.nombre_empresa', read_only=True)
    class Meta:
        model = ComprobanteEgreso
        fields = ['id', 'proveedor', 'proveedor_nombre', 'medio_pago', 'valor', 'nota', 'fecha']

class ClienteDetalleSerializer(serializers.ModelSerializer):
    observaciones = ObservacionClienteSerializer(many=True, read_only=True)
    class Meta:
        model = Cliente
        fields = ['id', 'nombre', 'cedula', 'correo', 'direccion', 'ciudad', 'telefono1', 'telefono2', 'observaciones']

class VentaDetalleSerializer(serializers.ModelSerializer):
    cliente = ClienteDetalleSerializer(read_only=True)
    observaciones_venta = ObservacionVentaSerializer(many=True, read_only=True, source='observaciones')
    recibos = ReciboCajaSerializer(many=True, read_only=True)
    remisiones = RemisionSerializer(many=True, read_only=True)
    ordenes_pedido = OrdenPedidoSerializer(many=True, read_only=True)
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    
    class Meta:
        model = Venta
        fields = [
            'id', 'cliente', 'vendedor', 'valor_total', 'abono', 'saldo', 
            'fecha_venta', 'fecha_entrega', 'estado', 'estado_pedidos', 
            'observaciones_venta', 'recibos', 'remisiones', 'ordenes_pedido', 
            'vendedor_nombre', 'cliente_nombre'
        ]