from .permissions import tiene_permiso_codigo
from rest_framework import serializers
from suministros.models import Subcategoria
from suministros.recepcion import recibidas_de
import logging
from decimal import Decimal
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    CustomUser, Referencia, Proveedor, OrdenPedido, DetallePedido, Cliente, Venta, LineaVenta,
    ObservacionVenta, ObservacionCliente, Remision, ReciboCaja, PagoReciboCaja, ComprobanteReciboCaja, Caja, ComprobanteEgreso,
    ProveedorTela, PedidoTela, DetallePedidoTela, DireccionEntrega
)

class UserManageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'first_name', 'last_name', 'role', 'is_active', 'password', 'acceso_rapido_ia']
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
        if not instance.date_joined:
            # Algunas cuentas antiguas fueron insertadas directo en la BD (fuera
            # del ORM) sin `date_joined`, y esa columna es NOT NULL: guardar la
            # instancia tal cual revienta con IntegrityError. Se rellena aquí
            # con un valor razonable en vez de dejar la edición del usuario rota.
            instance.date_joined = timezone.now()
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
    # Unidades ya recibidas por factura contra esta línea (P11-01).
    recibidas = serializers.SerializerMethodField()
    rechazadas = serializers.SerializerMethodField()

    subcategoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model = DetallePedido
        fields = ['id', 'cantidad', 'especificaciones', 'referencia', 'referencia_nombre', 'subcategoria', 'subcategoria_nombre',
                  'recibidas', 'rechazadas', 'linea_venta']

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria_id else ''

    def get_rechazadas(self, obj):
        n = getattr(obj, 'n_rechazadas', None)
        return n if n is not None else sum(r.cantidad for r in obj.rechazos.all())

    def get_recibidas(self, obj):
        n = getattr(obj, 'n_recibidas', None)
        return n if n is not None else recibidas_de(obj)

    def get_referencia(self, obj):
        # La referencia puede haber sido eliminada del catálogo (SET_NULL): no debe romper
        # la visualización de órdenes históricas que ya usaron ese producto.
        return obj.referencia.nombre if obj.referencia else "N/A"

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else "N/A"

class SinCostoSinPermisoMixin:
    """Quita `costo` de la respuesta salvo que el contexto indique permiso
    (VER_COSTOS_ORDEN). Ocultar la columna en React no protege la API (H06)."""
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get('ver_costos', False):
            data.pop('costo', None)
        return data


class SinMargenSinPermisoMixin:
    """Quita `costo_estimado`, `margen` y `margen_total` de la respuesta salvo que el contexto
    indique permiso (VER_MARGENES). Ocultar en React no protege la API (P12-01)."""
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get('ver_margenes', False):
            data.pop('costo_estimado', None)
            data.pop('margen', None)
            data.pop('margen_total', None)
        return data


class DetallePedidoWriteSerializer(serializers.ModelSerializer):
    """Alta/edición directa de un detalle: cantidad positiva y referencia del
    mismo proveedor de la orden (H27)."""
    cantidad = serializers.IntegerField(min_value=1, max_value=10000)

    class Meta:
        model = DetallePedido
        fields = ['id', 'orden', 'referencia', 'cantidad', 'especificaciones']

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.linea_venta_id:
            linea = instance.linea_venta
            Venta.objects.select_for_update().get(pk=linea.venta_id)
            instance = DetallePedido.objects.select_for_update().get(pk=instance.pk)
            otros = sum(linea.detalles.exclude(pk=instance.pk).exclude(orden__estado='anulado').values_list('cantidad', flat=True))
            cantidad = validated_data.get('cantidad', instance.cantidad)
            if cantidad + otros > linea.cantidad:
                raise serializers.ValidationError('La cantidad supera las unidades vendidas pendientes de pedir.')
            if validated_data.get('referencia', instance.referencia).pk != instance.referencia_id or validated_data.get('orden', instance.orden).pk != instance.orden_id:
                raise serializers.ValidationError('Una línea vinculada conserva su referencia y pedido de origen.')
        return super().update(instance, validated_data)

    def validate(self, attrs):
        orden = attrs.get('orden', getattr(self.instance, 'orden', None))
        referencia = attrs.get('referencia', getattr(self.instance, 'referencia', None))
        if referencia is None:
            raise serializers.ValidationError({'referencia': 'La referencia es obligatoria.'})
        if orden and referencia.proveedor_id != orden.proveedor_id:
            raise serializers.ValidationError({'referencia': 'La referencia no pertenece al proveedor de la orden.'})
        if self.instance is not None:
            recibidas = recibidas_de(self.instance)
            if recibidas and attrs.get('cantidad', self.instance.cantidad) < recibidas:
                raise serializers.ValidationError({'cantidad': f'Ya se recibieron {recibidas} unidades de esta línea.'})
            if recibidas and 'orden' in attrs and attrs['orden'].pk != self.instance.orden_id:
                raise serializers.ValidationError({'orden': 'La línea ya tiene unidades recibidas; no se mueve a otra orden.'})
        return attrs


def subcategoria_del_detalle(datos):
    """Completa y valida la subcategoría de un producto del pedido; devuelve el error o None."""
    ref, linea = datos['referencia'], datos.get('linea_venta')
    sub = datos.get('subcategoria')
    validas = set(ref.subcategorias.values_list('pk', flat=True))
    if sub is not None and sub.pk not in validas:
        return f'«{sub.nombre}» no es una subcategoría de {ref.nombre}.'
    if sub is None and linea is not None:
        # Producto de una venta: la subcategoría del producto vendido, si sigue en la referencia.
        vendida = linea.variante.subcategoria if linea.variante_id else None
        datos['subcategoria'] = vendida if vendida is not None and vendida.pk in validas else None
        return None
    if sub is None and validas:
        return f'Elige la subcategoría de {ref.nombre}.'
    return None


class DetalleOrdenEntradaSerializer(serializers.Serializer):
    referencia = serializers.PrimaryKeyRelatedField(queryset=Referencia.objects.all())
    # (2026-10-27) Subcategoría de la referencia (p. ej. Silla). Obligatoria si la referencia tiene
    # subcategorías; con línea de venta se toma la del producto vendido.
    subcategoria = serializers.PrimaryKeyRelatedField(queryset=Subcategoria.objects.all(), required=False, allow_null=True)
    cantidad = serializers.IntegerField(min_value=1, max_value=10000, default=1)
    especificaciones = serializers.CharField(allow_blank=True, required=False, default='-')
    # Línea de la venta que esta compra atiende (P09-03 / P11-04): mismo hilo de
    # identificadores de la cotización a la entrega.
    linea_venta = serializers.PrimaryKeyRelatedField(queryset=LineaVenta.objects.all(), required=False, allow_null=True)


class OrdenPedidoListSerializer(SinCostoSinPermisoMixin, serializers.ModelSerializer):
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
            'vendedor', 'orden_venta', 'es_exhibicion', 'es_feria_hogar', 'imagen_feria_hogar'
        ]

    def get_vendedor(self, obj):
        if obj.usuario and obj.usuario.first_name:
            return obj.usuario.first_name
        if obj.venta and obj.venta.vendedor and obj.venta.vendedor.first_name:
            return obj.venta.vendedor.first_name
        return None


class OrdenPedidoSerializer(SinCostoSinPermisoMixin, serializers.ModelSerializer):
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
            'vendedor', 'detalles', 'orden_venta', 'es_exhibicion', 'es_feria_hogar',
            'imagen_feria_hogar', 'telas_asociadas'
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
            proveedor = attrs.get('proveedor')
            detalles, errores = [], {}
            for idx, d in enumerate(detalles_raw):
                if not isinstance(d, dict) or not d.get('referencia'):
                    errores[idx] = {'referencia': 'Debe tener una referencia válida.'}
                    continue
                entrada = DetalleOrdenEntradaSerializer(data=d)
                if not entrada.is_valid():
                    errores[idx] = entrada.errors
                    continue
                ref = entrada.validated_data['referencia']
                if proveedor and ref.proveedor_id != proveedor.id:
                    errores[idx] = {'referencia': f'"{ref.nombre}" no pertenece al proveedor de la orden.'}
                    continue
                linea = entrada.validated_data.get('linea_venta')
                venta = attrs.get('venta')
                if linea is not None and (venta is None or linea.venta_id != venta.pk):
                    errores[idx] = {'linea_venta': 'La línea de venta no pertenece a la venta de la orden.'}
                    continue
                error = subcategoria_del_detalle(entrada.validated_data)
                if error:
                    errores[idx] = {'subcategoria': error}
                    continue
                detalles.append(entrada.validated_data)
            if errores:
                # Una fila inválida rechaza la orden completa, con el error por fila (U03).
                raise serializers.ValidationError({
                    'detalles': {f'producto_{i + 1}': e for i, e in errores.items()}
                })
            self._detalles_validados = detalles
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        venta = validated_data.get('venta')
        if venta:
            venta = Venta.objects.select_for_update().get(pk=venta.pk)
        cantidades = {}
        for d in self._detalles_validados:
            linea = d.get('linea_venta')
            if not linea:
                if venta and venta.revision_productos:
                    raise serializers.ValidationError('Selecciona los productos desde el desglose de la venta para conservar su vínculo.')
                continue
            linea = LineaVenta.objects.select_for_update().get(pk=linea.pk)
            if venta.revision_productos and not venta.productos_confirmados:
                raise serializers.ValidationError('Confirma los productos antes de pedirlos.')
            cantidades[linea.pk] = cantidades.get(linea.pk, 0) + d['cantidad']
            pedidas = sum(linea.detalles.exclude(orden__estado='anulado').values_list('cantidad', flat=True))
            if linea.inventario_origen_id or pedidas + cantidades[linea.pk] > linea.cantidad:
                raise serializers.ValidationError('La cantidad supera las unidades de venta pendientes de pedir.')
            if linea.referencia_id and linea.referencia_id != d['referencia'].pk:
                raise serializers.ValidationError('La referencia no coincide con la línea de venta.')
        orden = OrdenPedido.objects.create(**validated_data)
        DetallePedido.objects.bulk_create([
            DetallePedido(orden=orden, referencia=d['referencia'], subcategoria=d.get('subcategoria'), cantidad=d['cantidad'],
                          especificaciones=d.get('especificaciones') or '-', linea_venta=d.get('linea_venta'))
            for d in self._detalles_validados
        ])
        return orden

class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = '__all__'

class LineaVentaSerializer(SinMargenSinPermisoMixin, serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and not tiene_permiso_codigo(request, 'VER_PRECIOS_VENTA'):
            for key in ('precio_unitario', 'precio_lista_unitario', 'descuento', 'subtotal', 'adicionales', 'motivo_precio'):
                data.pop(key, None)
        return data

    margen = serializers.SerializerMethodField(read_only=True)

    def get_margen(self, obj):
        if obj.costo_estimado is not None:
            return (obj.subtotal - (obj.costo_estimado * obj.cantidad)).quantize(Decimal('0.01'))
        return None

    class Meta:
        model = LineaVenta
        fields = [
            'id', 'venta', 'variante', 'referencia', 'producto_nombre', 'variante_nombre',
            'categoria_nombre', 'grupo_tela', 'especificaciones', 'cantidad',
            'precio_unitario', 'descuento', 'subtotal', 'costo_estimado', 'margen',
            'fecha_compromiso', 'estado_entrega', 'opcionales', 'notas', 'created_at',
            'precio_lista_unitario', 'grupo_catalogo', 'texto_cliente', 'texto_proveedor', 'sin_texto_proveedor',
            'adicionales', 'motivo_precio', 'inventario_origen',
            'tipo', 'tela_modo', 'tela_material', 'tela_referencia', 'tela_color', 'tela_proveedor', 'tela_cantidad',
            'tela_grupo', 'tela_costo', 'conjunto', 'conjunto_nombre', 'conjunto_cantidad',
        ]
        read_only_fields = ['id', 'created_at', 'margen']

class VentaSerializer(SinMargenSinPermisoMixin, serializers.ModelSerializer):
    gestion = serializers.SerializerMethodField(read_only=True)

    def get_gestion(self, obj):
        from .gestion_venta import estado_gestion
        return estado_gestion(obj)

    def update(self, instance, validated_data):
        # D15a: el precio de lista es la suma de los productos (no se digita en la venta).
        # Si cambia el valor de la venta, se vuelve a repartir entre los productos.
        nuevo_total = validated_data.get('valor_total', instance.valor_total)
        lineas = list(instance.lineas.all()) if nuevo_total != instance.valor_total else []
        if lineas:
            from .productos_venta import repartir
            for linea, reparto in zip(lineas, repartir(Decimal(str(nuevo_total)), [(l.precio_lista_unitario or Decimal(0), l.cantidad, l.tipo) for l in lineas])):
                for campo, valor in reparto.items():
                    setattr(linea, campo, valor)
            LineaVenta.objects.bulk_update(lineas, ['precio_unitario', 'descuento', 'subtotal'])
            instance.revision_productos += 1
        # Ajuste manual de la gestión (Editar venta): queda quién y cuándo.
        if 'estado_pedidos' in validated_data and validated_data['estado_pedidos'] != instance.estado_pedidos:
            request = self.context.get('request')
            instance.gestion_finalizada_en = timezone.now() if validated_data['estado_pedidos'] else None
            instance.gestion_finalizada_por = request.user if validated_data['estado_pedidos'] and request else None
        return super().update(instance, validated_data)

    revision_productos = serializers.IntegerField(read_only=True)
    productos_confirmados = serializers.BooleanField(read_only=True)
    # Facturación: solo cambia por /ventas/<id>/facturada/ (MARCAR_VENTA_FACTURADA).
    facturada_por_nombre = serializers.SerializerMethodField(read_only=True)

    def get_facturada_por_nombre(self, obj):
        u = obj.facturada_por
        return (u.get_full_name() or u.username) if u else ''
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    vendedores_compartidos_nombres = serializers.SerializerMethodField(read_only=True)
    lineas = LineaVentaSerializer(many=True, read_only=True)
    margen_total = serializers.SerializerMethodField(read_only=True)
    
    def get_vendedores_compartidos_nombres(self, obj):
        return ", ".join([v.first_name for v in obj.vendedores_compartidos.all()])

    def get_margen_total(self, obj):
        lineas = list(obj.lineas.all())
        lineas_con_costo = [l for l in lineas if l.costo_estimado is not None]
        if not lineas_con_costo:
            return None
        return sum(
            ((l.subtotal - (l.costo_estimado * l.cantidad)) for l in lineas_con_costo),
            Decimal('0.00')
        ).quantize(Decimal('0.01'))
    
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
            'valor_lista', 'revision_productos', 'productos_confirmados',
            'abono', 
            'saldo', 
            'fecha_entrega',
            'estado',
            'estado_pedidos',
            'gestion',
            'es_feria_hogar',
            'es_postferia',
            'lineas',
            'margen_total',
            'facturada', 'facturada_en', 'facturada_por_nombre',
        ]
        read_only_fields = ['abono', 'margen_total', 'valor_lista', 'facturada', 'facturada_en'] # valor_lista = suma de los productos (D15a). El abono solo cambia vía recibos de caja; el saldo se recalcula en las vistas
        extra_kwargs = {
            'vendedores_compartidos': {'required': False, 'allow_empty': True},
            'valor_total': {'coerce_to_string': False},
            'valor_lista': {'coerce_to_string': False},
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

class PagoReciboCajaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PagoReciboCaja
        fields = ['id', 'metodo_pago', 'valor', 'estado', 'confirmacion']
        read_only_fields = ['id', 'estado', 'confirmacion']


class ComprobanteReciboCajaSerializer(serializers.ModelSerializer):
    subido_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = ComprobanteReciboCaja
        fields = ['id', 'url', 'creado_en', 'subido_por_nombre']

    def get_subido_por_nombre(self, obj):
        u = obj.subido_por
        return (u.first_name or u.username) if u else None


class ReciboCajaSerializer(serializers.ModelSerializer):
    vendedor_nombre = serializers.SerializerMethodField()
    pagos = PagoReciboCajaSerializer(many=True, read_only=True)
    comprobantes = ComprobanteReciboCajaSerializer(many=True, read_only=True)
    valor = serializers.SerializerMethodField()
    metodo_pago = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()

    class Meta:
        model = ReciboCaja
        fields = ['id', 'venta', 'fecha', 'nota', 'pagos', 'comprobantes', 'vendedor_nombre', 'valor', 'metodo_pago', 'estado']

    def get_vendedor_nombre(self, obj):
        venta = obj.venta
        if not venta:
            return None
        nombres = [venta.vendedor.first_name] if venta.vendedor and venta.vendedor.first_name else []
        nombres += [v.first_name for v in venta.vendedores_compartidos.all() if v.first_name]
        return ", ".join(nombres) if nombres else None

    def _pagos_list(self, obj):
        return list(obj.pagos.all())

    def get_valor(self, obj):
        return sum((p.valor for p in self._pagos_list(obj)), Decimal('0'))

    def get_metodo_pago(self, obj):
        pagos = self._pagos_list(obj)
        if len(pagos) == 1:
            return pagos[0].metodo_pago
        if len(pagos) > 1:
            return 'Múltiple'
        return None

    def get_estado(self, obj):
        pagos = self._pagos_list(obj)
        if not pagos:
            return 'Pendiente'
        estados = {p.estado for p in pagos}
        if estados == {'Anulado'}:
            return 'Anulado'
        if estados == {'Confirmado'}:
            return 'Confirmado'
        if 'Confirmado' in estados and len(pagos) > 1:
            return 'Parcial'
        return 'Pendiente'

from django.db import transaction, IntegrityError

class CajaSerializer(serializers.ModelSerializer):
    """Solo salida. Los movimientos se crean exclusivamente con
    ordenes.servicios.registrar_movimiento_caja (bloqueo de cuenta, importe
    positivo, saldo no negativo calculado en servidor)."""
    usuario_nombre = serializers.CharField(source='usuario.first_name', read_only=True)

    class Meta:
        model = Caja
        fields = ['id', 'fecha_hora', 'concepto', 'tipo', 'valor', 'total_acumulado', 'usuario', 'usuario_nombre']
        read_only_fields = fields

class ComprobanteEgresoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.SerializerMethodField()
    facturas_detalle = serializers.SerializerMethodField()
    pago_bancario = serializers.SerializerMethodField()

    def get_pago_bancario(self, obj):
        from pagos.beneficiarios import informacion_ce
        return informacion_ce(obj)

    class Meta:
        model = ComprobanteEgreso
        fields = ['id', 'proveedor', 'proveedor_nombre', 'proveedor_otro_nombre', 'medio_pago', 'estado', 'valor', 'descripcion', 'fecha', 'concepto', 'recibido_por', 'facturas_detalle', 'otros_conceptos', 'cuenta_destino', 'cuenta_destino_snapshot', 'proveedor_tela', 'pago_bancario']
        read_only_fields = ['cuenta_destino_snapshot']

    def get_proveedor_nombre(self, obj):
        try:
            if obj.proveedor:
                return obj.proveedor.nombre_empresa
            if obj.proveedor_tela_id:
                return obj.proveedor_tela.nombre_empresa
            return obj.proveedor_otro_nombre or None
        except Exception as e:
            logging.error(f'Error serializing proveedor_nombre for ComprobanteEgreso {obj.id}: {e}')
            return None

    def get_facturas_detalle(self, obj):
        try:
            # Si la vista de listado ya prefetcheó 'facturas__items_inventario__...' a nivel de
            # queryset, reutilizar ese caché en vez de volver a encadenar prefetch_related aquí
            # (encadenar sobre un related manager ya prefetcheado ignora el caché y dispara una
            # query nueva POR CADA comprobante — con 30 por página eso son ~90 queries extra).
            if 'facturas' in getattr(obj, '_prefetched_objects_cache', {}):
                facturas = obj.facturas.all()
            else:
                facturas = obj.facturas.all().prefetch_related(
                    'items_inventario__referencia', 'items_inventario__categoria', 'items_inventario__subcategoria'
                )
            result = []
            for f in facturas:
                productos = []
                # Los productos reales de una factura viven en Inventario (items_inventario);
                # DetalleFactura (related_name 'productos') es una tabla legada que el flujo
                # de creación de facturas ya no escribe (ver _crear_item_inventario).
                for p in f.items_inventario.all():
                    productos.append({
                        'id': p.id_referencia,
                        'referencia_nombre': p.referencia.nombre if p.referencia else 'Producto',
                        'categoria_nombre': p.categoria.nombre if p.categoria else '',
                        'subcategoria_nombre': p.subcategoria.nombre if p.subcategoria else '',
                        'variacion': p.variacion or '',
                        'costo': str(p.costo_especifico),
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
            logging.exception(f'Error serializing facturas_detalle for ComprobanteEgreso {obj.id}')
            return []

class ClienteDetalleSerializer(serializers.ModelSerializer):
    observaciones = ObservacionClienteSerializer(many=True, read_only=True)
    class Meta:
        model = Cliente
        fields = ['id', 'tipo_persona', 'nombre', 'cedula', 'correo', 'direccion', 'barrio', 'ciudad', 'telefono1', 'telefono2', 'observaciones']

class VentaDetalleSerializer(SinMargenSinPermisoMixin, serializers.ModelSerializer):
    gestion = serializers.SerializerMethodField(read_only=True)

    def get_gestion(self, obj):
        from .gestion_venta import estado_gestion
        return estado_gestion(obj)

    cliente = ClienteDetalleSerializer(read_only=True)
    observaciones_venta = ObservacionVentaSerializer(many=True, read_only=True, source='observaciones')
    # recibos = ReciboCajaSerializer(many=True, read_only=True) # REMOVED FOR PERFORMANCE
    remisiones = RemisionSerializer(many=True, read_only=True)
    ordenes_pedido = OrdenPedidoSerializer(many=True, read_only=True)
    lineas = LineaVentaSerializer(many=True, read_only=True)
    cotizaciones = serializers.SerializerMethodField(read_only=True)
    margen_total = serializers.SerializerMethodField(read_only=True)
    revision_productos = serializers.IntegerField(read_only=True)
    productos_confirmados = serializers.BooleanField(read_only=True)
    vendedor_nombre = serializers.CharField(source='vendedor.first_name', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    vendedores_compartidos_nombres = serializers.SerializerMethodField(read_only=True)

    def get_vendedores_compartidos_nombres(self, obj):
        return ", ".join([v.first_name for v in obj.vendedores_compartidos.all()])

    def get_margen_total(self, obj):
        lineas = list(obj.lineas.all())
        lineas_con_costo = [l for l in lineas if l.costo_estimado is not None]
        if not lineas_con_costo:
            return None
        return sum(
            ((l.subtotal - (l.costo_estimado * l.cantidad)) for l in lineas_con_costo),
            Decimal('0.00')
        ).quantize(Decimal('0.01'))

    def get_cotizaciones(self, obj):
        return [
            {
                'id': c.id,
                'numero': c.numero,
                'fecha_creacion': c.fecha_creacion,
                'total': c.total,
                'estado': c.estado,
            }
            for c in obj.cotizaciones.all()
        ]
    
    class Meta:
        model = Venta
        fields = [
            'id', 'cliente', 'vendedor', 'vendedores_compartidos', 'vendedores_compartidos_nombres', 
            'traslado', 'sede', 'valor_total', 'valor_lista', 'revision_productos', 'productos_confirmados', 'abono', 'saldo', 
            'fecha_venta', 'fecha_entrega', 'estado', 'estado_pedidos', 'gestion', 'es_postferia', 
            'observaciones_venta', 'remisiones', 'ordenes_pedido', 'lineas', 'cotizaciones',
            'margen_total', 'vendedor_nombre', 'cliente_nombre'
        ]

class ProveedorTelaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProveedorTela
        fields = '__all__'

class DetallePedidoTelaSerializer(serializers.ModelSerializer):
    # Producto de la venta al que corresponde esta tela (pedido hecho desde Ventas).
    linea_venta = serializers.PrimaryKeyRelatedField(queryset=LineaVenta.objects.all(), required=False, allow_null=True)

    class Meta:
        model = DetallePedidoTela
        fields = ['id', 'tela', 'cantidad', 'observacion', 'linea_venta']

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
    venta_vendedor_nombre = serializers.SerializerMethodField()
    venta = serializers.PrimaryKeyRelatedField(queryset=Venta.objects.all(), required=False, allow_null=True, write_only=True)
    anulado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = PedidoTela
        fields = [
            'id', 'usuario', 'usuario_nombre', 'proveedor', 'proveedor_nombre',
            'direccion_entrega', 'fecha_creacion', 'estado', 'observacion',
            'orden_asociada_id', 'detalles', 'orden_id', 'orden_proveedor_nombre', 'venta_id',
            'venta_vendedor_nombre', 'venta', 'motivo_anulacion', 'anulado_por_nombre', 'anulado_en'
        ]
        read_only_fields = ['fecha_creacion', 'usuario', 'id', 'motivo_anulacion', 'anulado_en']

    def get_anulado_por_nombre(self, obj):
        return obj.anulado_por.first_name if obj.anulado_por_id else None

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
        if obj.venta_id:
            return obj.venta_id
        return obj.orden_asociada.venta.id if obj.orden_asociada and obj.orden_asociada.venta else None

    def get_venta_vendedor_nombre(self, obj):
        venta = obj.venta or (obj.orden_asociada.venta if obj.orden_asociada else None)
        if not venta:
            return None
        nombres = [venta.vendedor.first_name] if venta.vendedor and venta.vendedor.first_name else []
        nombres += [v.first_name for v in venta.vendedores_compartidos.all() if v.first_name]
        return ", ".join(nombres) if nombres else None

    def _lineas_de_venta(self, validated_data, detalles_data):
        """Pedido hecho desde Ventas: los productos son de esa venta, visible para quien
        pide, y ninguno tiene ya su tela pedida (no se pide dos veces)."""
        from .permissions import ventas_visibles
        ids = [d['linea_venta'].pk for d in detalles_data if d.get('linea_venta')]
        venta = validated_data.get('venta')
        if not ids and not venta:
            return []
        lineas = {l.pk: l for l in LineaVenta.objects.select_for_update().filter(pk__in=ids)}
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError({'detalles': 'Un producto está repetido.'})
        venta = venta or next(iter(lineas.values())).venta
        if any(l.venta_id != venta.pk for l in lineas.values()):
            raise serializers.ValidationError({'detalles': 'Todos los productos deben ser de la misma venta.'})
        if not ventas_visibles(self.context['request']).filter(pk=venta.pk).exists():
            raise serializers.ValidationError({'venta': 'No puedes pedir telas para esta venta.'})
        ya = DetallePedidoTela.objects.filter(linea_venta_id__in=ids).exclude(pedido__estado=PedidoTela.ANULADO).select_related('linea_venta').first()
        if ya:
            raise serializers.ValidationError({'detalles': f'La tela de {ya.linea_venta.producto_nombre} ya se pidió (PT {ya.pedido_id}).'})
        validated_data['venta'] = venta
        return list(lineas.values())

    def _marcar_lineas(self, pedido, detalles_data):
        """El producto queda con lo que realmente se pidió (material, referencia, color,
        proveedor y cantidad) y la venta cambia de revisión."""
        from .servicios import auditar
        for d in detalles_data:
            linea = d.get('linea_venta')
            if not linea:
                continue
            texto = d['tela'].strip()
            cuero = texto.upper().startswith('[CUERO]')
            texto = texto[len('[CUERO]'):].strip() if cuero else texto
            referencia, _, color = texto.partition(' - Color: ')
            linea.tela_modo, linea.tela_material = LineaVenta.TELA_APARTE, 'cuero' if cuero else 'tela'
            linea.tela_referencia, linea.tela_color = referencia.strip()[:255], color.strip()[:255]
            linea.tela_proveedor, linea.tela_cantidad = pedido.proveedor, d['cantidad']
            linea.save(update_fields=['tela_modo', 'tela_material', 'tela_referencia', 'tela_color', 'tela_proveedor', 'tela_cantidad'])
        Venta.objects.filter(pk=pedido.venta_id).update(revision_productos=models.F('revision_productos') + 1)
        # En /ordenes la tela de la orden pasa a "Pedida" cuando ya se pidió la de todos sus productos.
        from .productos_venta import estado_tela_de
        ordenes = OrdenPedido.objects.filter(Q(pk=pedido.orden_asociada_id) | Q(detalles__linea_venta__detalles_tela__pedido=pedido)).distinct()
        for orden in ordenes.filter(tela__in=['Por pedir', 'Pendiente']):
            lineas = list(LineaVenta.objects.filter(detalles__orden=orden).select_related('variante').distinct())
            if lineas and estado_tela_de(lineas) == 'Pedida':
                orden.tela = 'Pedida'
                orden.save(update_fields=['tela'])
        auditar(self.context['request'].user, 'venta.tela_pedida', pedido,
                {'venta': pedido.venta_id, 'lineas': [d['linea_venta'].pk for d in detalles_data if d.get('linea_venta')]})

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

                    lineas = self._lineas_de_venta(validated_data, detalles_data)
                    pedido = PedidoTela.objects.create(id=new_id, usuario=usuario, **validated_data)

                    for detalle_data in detalles_data:
                        DetallePedidoTela.objects.create(pedido=pedido, **detalle_data)
                    if lineas:
                        self._marcar_lineas(pedido, detalles_data)

                    return pedido
            except IntegrityError:
                if attempt == 1:
                    raise
