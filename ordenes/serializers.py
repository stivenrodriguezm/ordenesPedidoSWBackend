from rest_framework import serializers
import logging
from django.db import transaction
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    CustomUser, Referencia, Proveedor, OrdenPedido, DetallePedido, Cliente, Venta,
    ObservacionVenta, ObservacionCliente, Remision, ReciboCaja, Caja, ComprobanteEgreso,
    ProveedorTela, PedidoTela, DetallePedidoTela, DireccionEntrega
)

class UserManageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'first_name', 'last_name', 'role', 'is_active', 'password']
        extra_kwargs = {
            'password': {'write_only': True, 'required': False}
        }

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = CustomUser(**validated_data)
        if password:
            try:
                validate_password(password, user)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
            user.set_password(password)
        else:
            # If no password is provided in creation (though the frontend should require it),
            # we generate an unusable password as fallback.
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            try:
                validate_password(password, instance)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
            instance.set_password(password)
        instance.save()
        return instance

class DireccionEntregaSerializer(serializers.ModelSerializer):
    class Meta:
        model = DireccionEntrega
        fields = ['id', 'nombre', 'detalles']

class ReferenciaSerializer(serializers.ModelSerializer):
    categorias_nombres = serializers.SerializerMethodField()
    subcategorias_nombres = serializers.SerializerMethodField()

    class Meta:
        model = Referencia
        fields = [
            'id', 'nombre', 'proveedor', 
            'categorias', 'categorias_nombres', 
            'subcategorias', 'subcategorias_nombres'
        ]

    def get_categorias_nombres(self, obj):
        return [c.nombre for c in obj.categorias.all()]

    def get_subcategorias_nombres(self, obj):
        return [s.nombre for s in obj.subcategorias.all()]

class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proveedor
        fields = ['id', 'nombre_empresa', 'nombre_encargado', 'contacto', 'dias_pago', 'porcentaje_descuento']

class DetallePedidoSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.SerializerMethodField()
    referencia = serializers.SerializerMethodField()

    class Meta:
        model = DetallePedido
        fields = ['id', 'cantidad', 'especificaciones', 'referencia', 'referencia_nombre']

    def get_referencia(self, obj):
        # La referencia puede haber sido eliminada del catálogo (SET_NULL): no debe romper
        # la visualización de órdenes históricas que ya usaron ese producto.
        return obj.referencia.nombre if obj.referencia else "N/A"

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else "N/A"

class OrdenPedidoListSerializer(serializers.ModelSerializer):
    """Serializer ligero para el listado de órdenes — sin N+1 queries.
    No incluye detalles ni telas_asociadas (se cargan bajo demanda al expandir).
    Requiere select_related('proveedor', 'usuario', 'venta__vendedor') en el queryset.
    """
    proveedor_nombre = serializers.CharField(source='proveedor.nombre_empresa', read_only=True)
    vendedor = serializers.SerializerMethodField()
    fecha_pedido = serializers.DateField(source='fecha_creacion', read_only=True)

    class Meta:
        model = OrdenPedido
        fields = [
            'id', 'proveedor_nombre', 'fecha_pedido', 'fecha_esperada',
            'estado', 'observacion', 'tela', 'venta', 'costo',
            'vendedor', 'orden_venta', 'es_exhibicion'
        ]

    def get_vendedor(self, obj):
        if obj.usuario and obj.usuario.first_name:
            return obj.usuario.first_name
        if obj.venta and obj.venta.vendedor and obj.venta.vendedor.first_name:
            return obj.venta.vendedor.first_name
        return None


class OrdenPedidoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.SerializerMethodField()
    vendedor = serializers.SerializerMethodField()
    detalles = DetallePedidoSerializer(many=True, read_only=True, required=False)
    fecha_pedido = serializers.DateField(source='fecha_creacion', read_only=True) # Mapea fecha_pedido a fecha_creacion
    telas_asociadas = serializers.SerializerMethodField()

    class Meta:
        model = OrdenPedido
        fields = [
            'id', 'proveedor', 'proveedor_nombre', 'fecha_pedido', 'fecha_esperada', 
            'estado', 'observacion', 'tela', 'venta', 'costo',
            'vendedor', 'detalles', 'orden_venta', 'es_exhibicion', 'telas_asociadas'
        ]
        extra_kwargs = {
            'proveedor': {'write_only': True, 'queryset': Proveedor.objects.all()},
            'venta': {'required': False, 'allow_null': True} 
        }

    def get_proveedor_nombre(self, obj):
        return obj.proveedor.nombre_empresa if obj.proveedor else None

    def get_vendedor(self, obj):
        if obj.usuario and obj.usuario.first_name:
            return obj.usuario.first_name
        if obj.venta and obj.venta.vendedor and obj.venta.vendedor.first_name:
            return obj.venta.vendedor.first_name
        return None

    def get_telas_asociadas(self, obj):
        # Si el queryset hizo prefetch de pedidos_telas__detalles, úsalo para evitar N+1
        prefetched = getattr(obj, '_prefetched_objects_cache', {})
        if 'pedidos_telas' in prefetched:
            detalles = sorted(
                (d for pedido in obj.pedidos_telas.all() for d in pedido.detalles.all()),
                key=lambda d: d.id,
            )
        else:
            from .models import DetallePedidoTela
            detalles = DetallePedidoTela.objects.filter(pedido__orden_asociada=obj)
        return DetallePedidoTelaSerializer(detalles, many=True).data

    def validate(self, attrs):
        if not self.instance:
            detalles_raw = self.initial_data.get('detalles', [])
            if not detalles_raw or not isinstance(detalles_raw, list) or len(detalles_raw) == 0:
                raise serializers.ValidationError({
                    "detalles": "No se puede crear una orden de pedido sin productos. Debe incluir al menos un producto."
                })
            for idx, d in enumerate(detalles_raw):
                if not isinstance(d, dict) or not d.get('referencia'):
                    raise serializers.ValidationError({
                        "detalles": f"El producto #{idx+1} debe tener una referencia válida."
                    })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        detalles_data = self.initial_data.get('detalles', [])
        orden = OrdenPedido.objects.create(**validated_data)
        for detalle_data in detalles_data:
            ref_id = detalle_data.get('referencia')
            cant = int(detalle_data.get('cantidad', 1))
            specs = detalle_data.get('especificaciones', '-')
            if ref_id:
                DetallePedido.objects.create(
                    orden=orden,
                    referencia_id=ref_id,
                    cantidad=cant,
                    especificaciones=specs
                )
        return orden

class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'

class VentaSerializer(serializers.ModelSerializer):
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    vendedores_compartidos_nombres = serializers.SerializerMethodField(read_only=True)
    
    def get_vendedores_compartidos_nombres(self, obj):
        return ", ".join([v.first_name for v in obj.vendedores_compartidos.all()])
    
    class Meta:
        model = Venta
        fields = [
            'id', 
            'fecha_venta', 
            'vendedor', 
            'vendedor_nombre', 
            'vendedores_compartidos',
            'vendedores_compartidos_nombres',
            'traslado',
            'sede',
            'cliente', 
            'cliente_nombre', 
            'valor_total', 
            'abono', 
            'saldo', 
            'fecha_entrega', 
            'estado', 
            'estado_pedidos'
        ]
        read_only_fields = ['abono'] # El abono solo cambia vía recibos de caja; el saldo se recalcula en las vistas
        extra_kwargs = {
            'vendedores_compartidos': {'required': False, 'allow_empty': True},
            'valor_total': {'coerce_to_string': False},
            'abono': {'coerce_to_string': False},
        }

class ObservacionVentaSerializer(serializers.ModelSerializer):
    autor_username = serializers.CharField(source='autor.username', read_only=True)

    class Meta:
        model = ObservacionVenta
        fields = ['id', 'texto', 'fecha', 'autor', 'autor_username', 'venta']
        read_only_fields = ['autor', 'fecha']

    def create(self, validated_data):
        validated_data['autor'] = self.context['request'].user
        return super().create(validated_data)

class ObservacionClienteSerializer(serializers.ModelSerializer):
    autor_username = serializers.CharField(source='autor.username', read_only=True)

    class Meta:
        model = ObservacionCliente
        fields = ['id', 'texto', 'fecha', 'autor', 'autor_username', 'cliente']
        read_only_fields = ['autor', 'fecha']

    def create(self, validated_data):
        validated_data['autor'] = self.context['request'].user
        return super().create(validated_data)
class RemisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Remision
        fields = '__all__'

class ReciboCajaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReciboCaja
        fields = '__all__'

from django.db import transaction, IntegrityError

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
            last_movement = Caja.objects.select_for_update().order_by('-fecha_hora', '-id').first()
            last_total = last_movement.total_acumulado if last_movement else 0

            if tipo == 'ingreso':
                new_total = last_total + valor
            elif tipo == 'egreso':
                if valor > last_total:
                    val_fmt = f"${float(valor):,.0f}".replace(',', '.')
                    bal_fmt = f"${float(last_total):,.0f}".replace(',', '.')
                    raise serializers.ValidationError({
                        "detail": f"Saldo insuficiente en caja. Saldo disponible en efectivo: {bal_fmt}. Intenta retirar: {val_fmt}."
                    })
                new_total = last_total - valor
            else:  # cierre
                new_total = valor
            
            validated_data['total_acumulado'] = new_total
            
            return super().create(validated_data)

class ComprobanteEgresoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.SerializerMethodField()
    facturas_detalle = serializers.SerializerMethodField()

    class Meta:
        model = ComprobanteEgreso
        fields = ['id', 'proveedor', 'proveedor_nombre', 'medio_pago', 'estado', 'valor', 'descripcion', 'fecha', 'concepto', 'recibido_por', 'facturas_detalle']

    def get_proveedor_nombre(self, obj):
        try:
            return obj.proveedor.nombre_empresa if obj.proveedor else None
        except Exception as e:
            logging.error(f'Error serializing proveedor_nombre for ComprobanteEgreso {obj.id}: {e}')
            return None

    def get_facturas_detalle(self, obj):
        try:
            facturas = getattr(obj, '_prefetched_facturas', None)
            if facturas is None:
                from suministros.models import FacturaProveedor
                facturas = FacturaProveedor.objects.filter(comprobante_egreso=obj).prefetch_related('productos__referencia')
            result = []
            for f in facturas:
                productos = []
                for p in f.productos.all():
                    productos.append({
                        'id': p.id,
                        'referencia_nombre': p.referencia.nombre if p.referencia else 'Producto',
                        'variacion': p.variacion or '',
                        'costo': str(p.costo),
                        'observacion': p.observacion or '',
                    })
                result.append({
                    'id': f.id,
                    'id_manual': f.id_manual,
                    'fecha_factura': f.fecha_factura.strftime('%Y-%m-%d') if f.fecha_factura else None,
                    'fecha_pago': str(f.fecha_pago) if f.fecha_pago else None,
                    'valor': str(f.valor),
                    'estado': f.estado,
                    'observaciones': f.observaciones or '',
                    'productos': productos,
                })
            return result
        except Exception:
            return []

class ClienteDetalleSerializer(serializers.ModelSerializer):
    observaciones = ObservacionClienteSerializer(many=True, read_only=True)
    class Meta:
        model = Cliente
        fields = ['id', 'nombre', 'cedula', 'correo', 'direccion', 'ciudad', 'telefono1', 'telefono2', 'observaciones']

class VentaDetalleSerializer(serializers.ModelSerializer):
    cliente = ClienteDetalleSerializer(read_only=True)
    observaciones_venta = ObservacionVentaSerializer(many=True, read_only=True, source='observaciones')
    # recibos = ReciboCajaSerializer(many=True, read_only=True) # REMOVED FOR PERFORMANCE
    remisiones = RemisionSerializer(many=True, read_only=True)
    ordenes_pedido = OrdenPedidoSerializer(many=True, read_only=True)
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    vendedores_compartidos_nombres = serializers.SerializerMethodField(read_only=True)

    def get_vendedores_compartidos_nombres(self, obj):
        return ", ".join([v.first_name for v in obj.vendedores_compartidos.all()])
    
    class Meta:
        model = Venta
        fields = [
            'id', 'cliente', 'vendedor', 'vendedores_compartidos', 'vendedores_compartidos_nombres', 
            'traslado', 'sede', 'valor_total', 'abono', 'saldo', 
            'fecha_venta', 'fecha_entrega', 'estado', 'estado_pedidos', 
            'observaciones_venta', 'remisiones', 'ordenes_pedido', 
            'vendedor_nombre', 'cliente_nombre'
        ]

class ProveedorTelaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProveedorTela
        fields = '__all__'

class DetallePedidoTelaSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetallePedidoTela
        fields = ['id', 'tela', 'cantidad', 'observacion']

class PedidoTelaSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()
    detalles = DetallePedidoTelaSerializer(many=True, required=False) # Nested serializer for details
    orden_asociada_id = serializers.PrimaryKeyRelatedField(
        queryset=OrdenPedido.objects.all(), source='orden_asociada', write_only=True, required=False, allow_null=True
    )
    orden_id = serializers.SerializerMethodField()
    orden_proveedor_nombre = serializers.SerializerMethodField()
    venta_id = serializers.SerializerMethodField()

    class Meta:
        model = PedidoTela
        fields = [
            'id', 'usuario', 'usuario_nombre', 'proveedor', 'proveedor_nombre', 
            'direccion_entrega', 'fecha_creacion', 'estado',  
            'orden_asociada_id', 'detalles', 'orden_id', 'orden_proveedor_nombre', 'venta_id'
        ]
        read_only_fields = ['fecha_creacion', 'usuario', 'id']

    def get_proveedor_nombre(self, obj):
        return obj.proveedor.nombre_empresa if obj.proveedor else None
        
    def get_orden_proveedor_nombre(self, obj):
        try:
            if obj.orden_asociada:
                if hasattr(obj.orden_asociada, 'proveedor') and obj.orden_asociada.proveedor:
                    return obj.orden_asociada.proveedor.nombre_empresa
                elif hasattr(obj.orden_asociada, 'proveedor_id') and obj.orden_asociada.proveedor_id:
                    prov = Proveedor.objects.filter(id=obj.orden_asociada.proveedor_id).first()
                    if prov:
                        return prov.nombre_empresa
        except Exception as e:
            logging.error(f"Error getting orden_proveedor_nombre for PedidoTela {obj.id}: {e}")
        return '-'

    def get_usuario_nombre(self, obj):
        return obj.usuario.first_name if obj.usuario else None
        
    def get_orden_id(self, obj):
        return obj.orden_asociada.id if obj.orden_asociada else None

    def get_venta_id(self, obj):
        return obj.orden_asociada.venta.id if obj.orden_asociada and obj.orden_asociada.venta else None

    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles', [])
        usuario = self.context['request'].user

        # Calculate next ID starting from 1000. select_for_update + retry
        # evita colisiones de PK cuando llegan dos creaciones concurrentes.
        for attempt in range(2):
            try:
                with transaction.atomic():
                    last_pedido = PedidoTela.objects.select_for_update().order_by('id').last()
                    if last_pedido:
                        new_id = max(last_pedido.id + 1, 1000)
                    else:
                        new_id = 1000

                    pedido = PedidoTela.objects.create(id=new_id, usuario=usuario, **validated_data)

                    for detalle_data in detalles_data:
                        DetallePedidoTela.objects.create(pedido=pedido, **detalle_data)

                    return pedido
            except IntegrityError:
                if attempt == 1:
                    raise