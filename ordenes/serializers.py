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
    fecha_creacion = serializers.DateField(read_only=True)

    class Meta:
        model = OrdenPedido
        fields = ['id', 'proveedor', 'fecha_creacion', 'fecha_esperada', 'estado', 'notas', 'orden_venta', 'detalles', 'costo', 'tela']  # Incluir 'tela'

    def create(self, validated_data):
        request = self.context.get('request')  # Obtener el contexto del request
        detalles_data = validated_data.pop('detalles', [])
        usuario = request.user if request else None  # Asignar el usuario autenticado
        orden = OrdenPedido.objects.create(usuario=usuario, **validated_data)
        for detalle_data in detalles_data:
            DetallePedido.objects.create(orden=orden, **detalle_data)
        return orden
    def validate_costo(self, value):
        try:
            value = float(value)  # Intenta convertir el valor a un número flotante
        except (TypeError, ValueError):
            raise serializers.ValidationError("El costo debe ser un número válido.")
        if value < 0:  # Opcional: valida que el costo no sea negativo
            raise serializers.ValidationError("El costo no puede ser negativo.")
        return value
    def validate_estado(self, value):
        if value not in dict(OrdenPedido.ESTADOS).keys():
            raise serializers.ValidationError("Estado inválido.")
        return value
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
