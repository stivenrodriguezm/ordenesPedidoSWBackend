from rest_framework import serializers
from .models import Referencia, Proveedor, OrdenPedido, DetallePedido

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
    class Meta:
        model = DetallePedido
        fields = ['cantidad', 'especificaciones', 'referencia']  # Excluimos 'orden' explícitamente


class OrdenPedidoSerializer(serializers.ModelSerializer):
    detalles = DetallePedidoSerializer(many=True, required=False)
    fecha_creacion = serializers.DateField(read_only=True)  # Campo de solo lectura

    class Meta:
        model = OrdenPedido
        fields = ['id', 'proveedor', 'fecha_creacion', 'fecha_esperada', 'estado', 'notas', 'orden_venta', 'detalles', 'costo']

    def validate(self, data):
        # Verificar que costo sea numérico
        if 'costo' in data and not isinstance(data['costo'], (int, float)):
            raise serializers.ValidationError({"costo": "El costo debe ser un número válido."})
        # Validar estado
        if 'estado' in data and data['estado'] not in dict(OrdenPedido.ESTADOS).keys():
            raise serializers.ValidationError({"estado": "Estado inválido."})
        return data

    def create(self, validated_data):
        request = self.context.get('request')  # Obtener el contexto del request
        detalles_data = validated_data.pop('detalles', [])
        usuario = request.user if request else None  # Asignar el usuario autenticado
        orden = OrdenPedido.objects.create(usuario=usuario, **validated_data)
        for detalle_data in detalles_data:
            DetallePedido.objects.create(orden=orden, **detalle_data)
        return orden

    def update(self, instance, validated_data):
        instance.costo = float(validated_data.get('costo', instance.costo)) if 'costo' in validated_data else instance.costo
        instance.estado = validated_data.get('estado', instance.estado)
        instance.save()
        return instance
