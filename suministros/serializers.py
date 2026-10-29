from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, AjusteFactura, RemisionSuministro, RemisionItemManual, RemisionEvento,
    RemisionInventarioTexto, GrupoInventario, GrupoInventarioComponente,
    Sede, Zona, HistorialTraslado, CostoAdicionalInventario,
    ItemInventarioTelaCuero
)
from ordenes.models import Venta, Referencia, DetallePedido
from ordenes.permissions import check_feature_permission
from . import movimientos, recepcion


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = '__all__'


class SubcategoriaSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.ReadOnlyField(source='categoria.nombre')

    class Meta:
        model = Subcategoria
        fields = '__all__'


# ---------------------------------------------------------------------------
# Sede y Zona
# ---------------------------------------------------------------------------
class SedeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sede
        fields = '__all__'

class ZonaSerializer(serializers.ModelSerializer):
    sede_nombre = serializers.ReadOnlyField(source='sede.nombre')

    class Meta:
        model = Zona
        fields = '__all__'

# ---------------------------------------------------------------------------
# GrupoInventario
# ---------------------------------------------------------------------------

class GrupoInventarioComponenteSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.ReadOnlyField(source='referencia.nombre')
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model = GrupoInventarioComponente
        fields = [
            'id', 'referencia', 'referencia_nombre',
            'categoria', 'categoria_nombre',
            'subcategoria', 'subcategoria_nombre',
            'variacion', 'cantidad',
        ]

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else None


class GrupoInventarioSerializer(serializers.ModelSerializer):
    componentes = GrupoInventarioComponenteSerializer(many=True, required=False)
    items_count = serializers.SerializerMethodField()
    costo_total = serializers.SerializerMethodField()
    subcategoria_id = serializers.PrimaryKeyRelatedField(
        source='subcategoria', 
        queryset=Subcategoria.objects.all(), 
        required=False, 
        allow_null=True
    )
    subcategoria_nombre = serializers.ReadOnlyField(source='subcategoria.nombre')
    categoria_id = serializers.PrimaryKeyRelatedField(
        source='categoria', 
        queryset=Categoria.objects.all(), 
        required=False, 
        allow_null=True
    )
    categoria_nombre = serializers.ReadOnlyField(source='categoria.nombre')
    venta_id = serializers.PrimaryKeyRelatedField(
        source='venta', 
        queryset=Venta.objects.all(), 
        required=False, 
        allow_null=True
    )

    class Meta:
        model = GrupoInventario
        fields = [
            'id', 'nombre', 'descripcion', 'activo', 'componentes', 
            'items_count', 'costo_total', 'categoria_id', 'categoria_nombre', 'subcategoria_id', 'subcategoria_nombre', 'observacion', 'venta_id'
        ]

    def get_items_count(self, obj):
        return obj.items_inventario.count()

    def get_costo_total(self, obj):
        return sum(item.costo_especifico for item in obj.items_inventario.all())

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not puede_ver_costos_inventario(self):
            data.pop('costo_total', None)
        return data

    def create(self, validated_data):
        componentes_data = validated_data.pop('componentes', [])
        grupo = GrupoInventario.objects.create(**validated_data)
        for comp in componentes_data:
            GrupoInventarioComponente.objects.create(grupo=grupo, **comp)
        return grupo

    def update(self, instance, validated_data):
        componentes_data = validated_data.pop('componentes', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if componentes_data is not None:
            instance.componentes.all().delete()
            for comp in componentes_data:
                GrupoInventarioComponente.objects.create(grupo=instance, **comp)
        return instance


# ---------------------------------------------------------------------------
# CostoAdicional
# ---------------------------------------------------------------------------

class CostoAdicionalInventarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostoAdicionalInventario
        fields = ['id', 'inventario', 'descripcion', 'valor', 'fecha']
        read_only_fields = ['id']


class ItemInventarioTelaCueroSerializer(serializers.ModelSerializer):
    costo_total = serializers.ReadOnlyField()

    class Meta:
        model = ItemInventarioTelaCuero
        fields = ['id', 'inventario', 'tipo', 'referencia', 'color', 'unidad_medida', 'costo_unidad', 'cantidad', 'costo_total']
        read_only_fields = ['id', 'costo_total']


# ---------------------------------------------------------------------------
# Inventario (tabla principal)
# ---------------------------------------------------------------------------

CAMPOS_COSTO_INVENTARIO = ('costo_especifico', 'costo_total', 'tela_costo_metro', 'costos_adicionales')


def puede_ver_costos_inventario(serializer):
    """Contexto explícito o permiso del usuario de la petición; sin petición
    (uso interno) se muestran."""
    if 'ver_costos' in serializer.context:
        return serializer.context['ver_costos']
    request = serializer.context.get('request')
    return request is None or tiene_permiso(request, 'VER_COSTOS_INVENTARIO')


def quitar_costos(data):
    """Elimina del cuerpo los costos (también en telas anidadas): ocultar la
    columna en React no protege la API (H06)."""
    for campo in CAMPOS_COSTO_INVENTARIO:
        data.pop(campo, None)
    for tc in data.get('telas_cueros') or []:
        tc.pop('costo_unidad', None)
        tc.pop('costo_total', None)
    return data


class InventarioSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.SerializerMethodField()
    categoria_id = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()
    proveedor_id = serializers.SerializerMethodField()
    proveedor_nombre = serializers.SerializerMethodField()
    factura_id_manual = serializers.SerializerMethodField()
    factura_id = serializers.SerializerMethodField()
    venta_numero = serializers.SerializerMethodField()
    grupo_id = serializers.SerializerMethodField()
    grupo_nombre = serializers.SerializerMethodField()
    zona_nombre = serializers.SerializerMethodField()
    sede_nombre = serializers.SerializerMethodField()
    costo_total = serializers.SerializerMethodField()

    class Meta:
        model = Inventario
        fields = '__all__'
        extra_fields = ['producto_nombre', 'categoria_id', 'categoria_nombre',
                        'subcategoria_nombre', 'proveedor_id', 'proveedor_nombre',
                        'factura_id_manual', 'factura_id', 'venta_numero',
                        'grupo_id', 'grupo_nombre', 'zona_nombre', 'sede_nombre',
                        'zona', 'venta_id', 'imagen', 'lleva_tela', 'tela_referencia',
                        'tela_color', 'tela_costo_metro', 'tela_cantidad_metros', 'vendedor_nombre'
        ]

    def get_producto_nombre(self, obj):
        if obj.referencia:
            return obj.referencia.nombre
        return None

    def get_categoria_id(self, obj):
        if obj.categoria:
            return obj.categoria.id
        return None

    def get_categoria_nombre(self, obj):
        if obj.categoria:
            return obj.categoria.nombre
        return None

    def get_subcategoria_nombre(self, obj):
        if obj.subcategoria:
            return obj.subcategoria.nombre
        return None

    def get_proveedor_id(self, obj):
        if obj.referencia and obj.referencia.proveedor:
            return obj.referencia.proveedor.id
        if obj.factura and obj.factura.proveedor:
            return obj.factura.proveedor.id
        return None

    def get_proveedor_nombre(self, obj):
        if obj.referencia and obj.referencia.proveedor:
            return obj.referencia.proveedor.nombre_empresa
        if obj.factura and obj.factura.proveedor:
            return obj.factura.proveedor.nombre_empresa
        return None

    def get_factura_id_manual(self, obj):
        if obj.factura:
            return obj.factura.id_manual
        if obj.factura_manual:
            return obj.factura_manual
        return None

    def get_factura_id(self, obj):
        return obj.factura.id if obj.factura else None

    def get_venta_numero(self, obj):
        return obj.venta.id if obj.venta else None

    def get_grupo_id(self, obj):
        return obj.grupo.id if obj.grupo else None

    def get_grupo_nombre(self, obj):
        return obj.grupo.nombre if obj.grupo else None

    def get_zona_nombre(self, obj):
        return obj.zona.nombre if obj.zona else None

    def get_sede_nombre(self, obj):
        try:
            return obj.zona.sede.nombre if obj.zona and obj.zona.sede else None
        except Exception:
            return None

    def get_costo_total(self, obj):
        from .costos import costo_integral
        return costo_integral(obj)

    def get_vendedor_nombre(self, obj):
        try:
            if getattr(obj, 'venta', None):
                vendedores = []
                vendedor = getattr(obj.venta, 'vendedor', None)
                if vendedor:
                    nombre = f"{getattr(vendedor, 'first_name', '')} {getattr(vendedor, 'last_name', '')}".strip() or getattr(vendedor, 'username', '')
                    if nombre:
                        vendedores.append(nombre)
                if hasattr(obj.venta, 'vendedores_compartidos'):
                    for vc in obj.venta.vendedores_compartidos.all():
                        nombre = f"{getattr(vc, 'first_name', '')} {getattr(vc, 'last_name', '')}".strip() or getattr(vc, 'username', '')
                        if nombre and nombre not in vendedores:
                            vendedores.append(nombre)
                return " y ".join(vendedores) if vendedores else None
        except Exception:
            return None
        return None

    def validate(self, attrs):
        # Quien no ve costos tampoco los escribe: su formulario los reenvía
        # vacíos y no deben pisar el costo real del ítem.
        if not puede_ver_costos_inventario(self):
            for campo in ('costo_especifico', 'tela_costo_metro'):
                attrs.pop(campo, None)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        try:
            data['costos_adicionales'] = CostoAdicionalInventarioSerializer(instance.costos_adicionales.all(), many=True).data
        except Exception:
            data['costos_adicionales'] = []
        try:
            data['telas_cueros'] = ItemInventarioTelaCueroSerializer(instance.telas_cueros.all(), many=True).data
        except Exception:
            data['telas_cueros'] = []
        if not puede_ver_costos_inventario(self):
            quitar_costos(data)
        return data

class HistorialTrasladoSerializer(serializers.ModelSerializer):
    item_referencia = serializers.ReadOnlyField(source='item_inventario.id_referencia')
    zona_origen_nombre = serializers.ReadOnlyField(source='zona_origen.nombre')
    zona_destino_nombre = serializers.ReadOnlyField(source='zona_destino.nombre')
    usuario_nombre = serializers.ReadOnlyField(source='usuario.username')

    class Meta:
        model = HistorialTraslado
        fields = '__all__'


# ---------------------------------------------------------------------------
# Nested read-only serializer: items del inventario dentro de una factura
# ---------------------------------------------------------------------------

class FacturasInventarioReadSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()
    venta_id = serializers.SerializerMethodField()
    grupo_nombre = serializers.SerializerMethodField()
    grupo_id = serializers.SerializerMethodField()
    grupo_categoria_nombre = serializers.SerializerMethodField()
    grupo_subcategoria_nombre = serializers.SerializerMethodField()
    vendedor_nombre = serializers.SerializerMethodField()
    zona_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Inventario
        fields = [
            'id_referencia', 'referencia', 'referencia_nombre',
            'categoria', 'categoria_nombre',
            'subcategoria', 'subcategoria_nombre',
            'variacion', 'costo_especifico', 'observacion',
            'disponibilidad', 'estado_fisico', 'venta', 'venta_id', 'imagen', 'fecha_ingreso', 'grupo_nombre', 'grupo_id',
            'grupo_categoria_nombre', 'grupo_subcategoria_nombre',
            'zona', 'zona_nombre',
            'lleva_tela', 'tela_referencia', 'tela_color', 'tela_costo_metro', 'tela_cantidad_metros', 'vendedor_nombre',
            'pedido', 'detalle_pedido',
        ]

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else None

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else None

    def get_grupo_id(self, obj):
        return obj.grupo.id if obj.grupo else None

    def get_venta_id(self, obj):
        return str(obj.venta.id) if obj.venta else None

    def get_grupo_nombre(self, obj):
        return obj.grupo.nombre if obj.grupo else None

    def get_zona_nombre(self, obj):
        return obj.zona.nombre if obj.zona else None

    def get_grupo_categoria_nombre(self, obj):
        return obj.grupo.categoria.nombre if obj.grupo and obj.grupo.categoria else None

    def get_grupo_subcategoria_nombre(self, obj):
        return obj.grupo.subcategoria.nombre if obj.grupo and obj.grupo.subcategoria else None

    def get_vendedor_nombre(self, obj):
        if obj.venta:
            vendedores = []
            if obj.venta.vendedor:
                nombre = f"{obj.venta.vendedor.first_name} {obj.venta.vendedor.last_name}".strip() or obj.venta.vendedor.username
                vendedores.append(nombre)
            for vc in obj.venta.vendedores_compartidos.all():
                nombre = f"{vc.first_name} {vc.last_name}".strip() or vc.username
                if nombre not in vendedores:
                    vendedores.append(nombre)
            return " y ".join(vendedores) if vendedores else None
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        try:
            data['telas_cueros'] = ItemInventarioTelaCueroSerializer(instance.telas_cueros.all(), many=True).data
        except Exception:
            data['telas_cueros'] = []
        return data


# ---------------------------------------------------------------------------
# DetalleFactura (kept for backward compatibility with existing records)
# ---------------------------------------------------------------------------

class DetalleFacturaListSerializer(serializers.ListSerializer):
    """Precarga las Ventas referenciadas por venta_id (CharField, no FK)
    en una sola query para evitar N+1 en get_vendedor_nombre."""
    def to_representation(self, data):
        from ordenes.models import Venta
        items = list(data.all() if hasattr(data, 'all') else data)
        venta_ids = [d.venta_id for d in items if d.venta_id]
        self._ventas_cache = {
            str(v.id): v
            for v in Venta.objects.filter(id__in=venta_ids)
            .select_related('vendedor')
            .prefetch_related('vendedores_compartidos')
        }
        return super().to_representation(items)


class DetalleFacturaSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()
    vendedor_nombre = serializers.SerializerMethodField()

    class Meta:
        model = DetalleFactura
        fields = '__all__'
        read_only_fields = ('factura',)
        list_serializer_class = DetalleFacturaListSerializer

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else None

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else None

    def get_vendedor_nombre(self, obj):
        if obj.venta_id:
            try:
                ventas_cache = getattr(self.parent, '_ventas_cache', None) if self.parent is not None else None
                if ventas_cache is not None:
                    venta = ventas_cache.get(str(obj.venta_id))
                    if venta is None:
                        return None
                else:
                    from ordenes.models import Venta
                    venta = Venta.objects.get(id=obj.venta_id)
                vendedores = []
                if venta.vendedor:
                    nombre = f"{venta.vendedor.first_name} {venta.vendedor.last_name}".strip() or venta.vendedor.username
                    vendedores.append(nombre)
                for vc in venta.vendedores_compartidos.all():
                    nombre = f"{vc.first_name} {vc.last_name}".strip() or vc.username
                    if nombre not in vendedores:
                        vendedores.append(nombre)
                return " y ".join(vendedores) if vendedores else None
            except Exception:
                pass
        return None


# ---------------------------------------------------------------------------
# Productos de factura: entrada tipada (P04-02, H11) y edición por identidad
# (P04-01, H04)
# ---------------------------------------------------------------------------

DISPONIBILIDADES = {c[0] for c in Inventario.DISPONIBILIDAD_CHOICES}
ESTADOS_FISICOS = {c[0] for c in Inventario.ESTADO_FISICO_CHOICES}
# Estados en los que la unidad ya está comprometida con una entrega: la
# edición de la factura no puede borrarla ni cambiar su venta/disponibilidad.
DISPONIBILIDAD_PROTEGIDA = {'por_despachar', 'despachado', 'entregado'}


class TelaCueroEntradaSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=[c[0] for c in ItemInventarioTelaCuero.TIPO_CHOICES], default='tela')
    referencia = serializers.CharField(allow_blank=True, required=False, default='', max_length=100)
    color = serializers.CharField(allow_blank=True, required=False, default='', max_length=50)
    unidad_medida = serializers.ChoiceField(choices=[c[0] for c in ItemInventarioTelaCuero.UNIDAD_CHOICES], required=False)
    costo_unidad = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), default=0)
    cantidad = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('10000'), default=0)

    def validate(self, attrs):
        attrs.setdefault('unidad_medida', 'metro' if attrs.get('tipo') == 'tela' else 'decimetro')
        return attrs


def _alias(datos, *claves):
    for k in claves:
        if k in datos and datos[k] not in (None, ''):
            return datos[k]
    return None


class ProductoFacturaSerializer(serializers.Serializer):
    """Una fila del formulario de factura: `cantidad` unidades iguales. Con
    `id_referencias` (o `id_referencia`) la fila actualiza esas unidades
    existentes en vez de crear otras."""
    id_referencias = serializers.ListField(child=serializers.CharField(max_length=50), required=False, default=list)
    referencia = serializers.PrimaryKeyRelatedField(queryset=Referencia.objects.all())
    categoria = serializers.PrimaryKeyRelatedField(queryset=Categoria.objects.all(), required=False, allow_null=True)
    subcategoria = serializers.PrimaryKeyRelatedField(queryset=Subcategoria.objects.all(), required=False, allow_null=True)
    variacion = serializers.CharField(allow_blank=True, required=False, max_length=255)
    costo = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    cantidad = serializers.IntegerField(min_value=1, max_value=500, default=1)
    grupo = serializers.PrimaryKeyRelatedField(queryset=GrupoInventario.objects.all(), required=False, allow_null=True)
    observacion = serializers.CharField(allow_blank=True, required=False)
    disponibilidad = serializers.ChoiceField(choices=sorted(DISPONIBILIDADES), required=False)
    estado_fisico = serializers.ChoiceField(choices=sorted(ESTADOS_FISICOS), required=False)
    zona = serializers.PrimaryKeyRelatedField(queryset=Zona.objects.all(), required=False, allow_null=True)
    venta = serializers.PrimaryKeyRelatedField(queryset=Venta.objects.all(), required=False, allow_null=True)
    # Línea de la orden de pedido que se recibe con esta fila (P11-01).
    detalle_pedido = serializers.PrimaryKeyRelatedField(
        queryset=DetallePedido.objects.select_related('orden'), required=False, allow_null=True)
    imagen = serializers.URLField(required=False, allow_null=True, allow_blank=True, max_length=500)
    telas_cueros = TelaCueroEntradaSerializer(many=True, required=False)
    tela_referencia = serializers.CharField(allow_blank=True, required=False, max_length=100)
    tela_color = serializers.CharField(allow_blank=True, required=False, max_length=50)
    tela_costo_metro = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False)
    tela_cantidad_metros = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal('0'), required=False)
    lleva_tela = serializers.BooleanField(required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('Cada producto debe ser un objeto.')
        datos = dict(data)
        # Nombres alternativos que el frontend ha usado históricamente.
        for destino, origenes in (
            ('grupo', ('grupo_id', 'grupo')), ('zona', ('zona', 'zona_id')),
            ('venta', ('venta_id', 'venta')), ('telas_cueros', ('telas_cueros', 'telasCueros')),
            ('detalle_pedido', ('detalle_pedido', 'detalle_pedido_id')),
            ('tela_referencia', ('tela_referencia', 'telaReferencia')), ('tela_color', ('tela_color', 'telaColor')),
            ('tela_costo_metro', ('tela_costo_metro', 'telaCostoMetro')),
            ('tela_cantidad_metros', ('tela_cantidad_metros', 'telaCantidadMetros')),
        ):
            valor = _alias(datos, *origenes)
            for o in origenes:
                datos.pop(o, None)
            if valor is not None:
                datos[destino] = valor
        if datos.get('id_referencia') and not datos.get('id_referencias'):
            datos['id_referencias'] = [datos['id_referencia']]
        datos.pop('id_referencia', None)
        return super().to_internal_value(datos)

    def validate(self, attrs):
        factura_proveedor = self.context.get('proveedor')
        ref = attrs['referencia']
        if factura_proveedor is not None and ref.proveedor_id != factura_proveedor.id:
            raise serializers.ValidationError({'referencia': f'"{ref.nombre}" no pertenece al proveedor de la factura.'})
        cat, sub = attrs.get('categoria'), attrs.get('subcategoria')
        if sub and cat and sub.categoria_id != cat.id:
            raise serializers.ValidationError({'subcategoria': f'"{sub.nombre}" no pertenece a la categoría {cat.nombre}.'})
        if sub and not cat:
            attrs['categoria'] = sub.categoria
        if len(attrs['id_referencias']) > attrs['cantidad']:
            raise serializers.ValidationError({'cantidad': 'La cantidad no puede ser menor que las unidades existentes de la fila.'})
        if 'detalle_pedido' in attrs:
            self._validar_linea_pedido(attrs, factura_proveedor)
        if attrs.get('disponibilidad') in movimientos.SOLO_POR_PROCESO and attrs['cantidad'] > len(attrs['id_referencias']):
            raise serializers.ValidationError({'disponibilidad': 'Una unidad nueva no puede ingresar con esa disponibilidad.'})
        return attrs

    @staticmethod
    def _validar_linea_pedido(attrs, proveedor):
        """La fila recibe una línea de orden de pedido del mismo proveedor; la
        venta de la orden se hereda (y no puede contradecirse)."""
        linea = attrs['detalle_pedido']
        if linea is None:
            attrs['pedido'] = None
            return
        orden = linea.orden
        if orden.estado == 'anulado':
            raise serializers.ValidationError({'detalle_pedido': f'La orden de pedido #{orden.pk} está anulada.'})
        if proveedor is not None and orden.proveedor_id != proveedor.id:
            raise serializers.ValidationError({'detalle_pedido': f'La orden de pedido #{orden.pk} es de otro proveedor.'})
        venta = attrs.get('venta')
        if orden.venta_id:
            if venta is not None and venta.pk != orden.venta_id:
                raise serializers.ValidationError({'venta': (
                    f'La orden de pedido #{orden.pk} es de la venta {orden.venta_id}; la fila indica la venta {venta.pk}.')})
            if venta is None:
                attrs['venta'] = orden.venta
                attrs.setdefault('disponibilidad', 'cliente')
        attrs['pedido'] = orden


VALORES_INICIALES = {
    'variacion': '', 'observacion': '', 'disponibilidad': 'exhibicion', 'estado_fisico': 'buen_estado',
    'tela_referencia': '', 'tela_color': '', 'tela_costo_metro': Decimal('0'), 'tela_cantidad_metros': Decimal('0'),
}
_CAMPOS_DIRECTOS = ('referencia', 'categoria', 'subcategoria', 'variacion', 'observacion', 'disponibilidad',
                    'estado_fisico', 'zona', 'venta', 'grupo', 'tela_costo_metro', 'tela_cantidad_metros',
                    'detalle_pedido', 'pedido')


def _valores_item(prod, crear):
    """Campos del modelo a escribir. Al crear se completan los valores iniciales;
    al editar solo se tocan los campos que la fila envía."""
    datos = {**VALORES_INICIALES, **prod} if crear else dict(prod)
    valores = {c: datos[c] for c in _CAMPOS_DIRECTOS if c in datos}
    valores['costo_especifico'] = datos['costo']
    if 'imagen' in datos:
        valores['imagen'] = datos['imagen'] or None
    for c in ('tela_referencia', 'tela_color'):
        if c in datos:
            valores[c] = datos[c] or None
    if crear or 'lleva_tela' in datos:
        valores['lleva_tela'] = bool(datos.get('lleva_tela') or datos.get('tela_referencia') or datos.get('tela_color')
                                     or (datos.get('tela_costo_metro') or 0) > 0)
    return valores


def _guardar_telas(item, prod, reemplazar):
    telas = prod.get('telas_cueros')
    if telas is None and not reemplazar:
        return
    if reemplazar and telas is not None:
        item.telas_cueros.all().delete()
    if telas:
        ItemInventarioTelaCuero.objects.bulk_create([ItemInventarioTelaCuero(inventario=item, **tc) for tc in telas])
    elif telas is None and not reemplazar and item.lleva_tela and (item.tela_referencia or item.tela_color or (item.tela_costo_metro or 0) > 0):
        ItemInventarioTelaCuero.objects.create(
            inventario=item, tipo='tela', referencia=item.tela_referencia or '', color=item.tela_color or '',
            unidad_medida='metro', costo_unidad=item.tela_costo_metro, cantidad=item.tela_cantidad_metros,
        )


def _crear_unidades(prod, factura, cantidad, usuario=None):
    from .identificadores import siguiente_id_inventario
    valores = _valores_item(prod, crear=True)
    categoria = valores.get('categoria')
    prefijo = categoria.nombre[:2].upper() if categoria and categoria.nombre else 'XX'
    for _ in range(cantidad):
        item = Inventario.objects.create(
            id_referencia=siguiente_id_inventario(prefijo), factura=factura,
            factura_manual=factura.id_manual or '', **valores,
        )
        movimientos.ingreso(item, usuario, documento=f'factura:{factura.pk}')
        _guardar_telas(item, prod, reemplazar=False)


def unidad_protegida(item):
    """Motivo por el que la unidad no puede eliminarse desde la factura, o ''."""
    if item.disponibilidad in DISPONIBILIDAD_PROTEGIDA:
        return f'está {item.get_disponibilidad_display().lower()}'
    if item.remisiones_suministros.exists():
        return 'está en una remisión'
    if item.historial_traslados.exists():
        return 'tiene historial de traslados'
    if item.movimientos.exclude(tipo__in=('ingreso', 'edicion')).exists():
        return 'tiene movimientos de inventario registrados'
    if item.costos_adicionales.exists():
        return 'tiene costos adicionales registrados'
    return ''


def _actualizar_unidad(item, prod, usuario=None):
    valores = _valores_item(prod, crear=False)
    comprometida = item.disponibilidad in DISPONIBILIDAD_PROTEGIDA or item.remisiones_suministros.filter(
        estado__in=REMISION_ESTADOS_ACTIVOS).exists()
    if comprometida:
        cambia_disp = 'disponibilidad' in valores and valores['disponibilidad'] != item.disponibilidad
        cambia_venta = 'venta' in valores and (valores['venta'].pk if valores['venta'] else None) != item.venta_id
        if cambia_disp or cambia_venta:
            raise serializers.ValidationError({'productos': f'El producto {item.pk} está comprometido en una entrega: '
                                                            'su venta y disponibilidad no se cambian desde la factura.'})
    try:
        movimientos.validar_edicion_manual(item, valores.get('disponibilidad'), False, en_remision_activa=False)
    except serializers.ValidationError as e:
        raise serializers.ValidationError({'productos': e.detail['disponibilidad']})
    antes = movimientos.foto(item)
    zona_anterior = item.zona
    for campo, valor in valores.items():
        setattr(item, campo, valor)
    item.save()
    movimientos.registrar(item, antes, 'edicion', usuario, motivo='Edición de la factura', documento=f'factura:{item.factura_id}')
    if 'zona' in valores and (zona_anterior and zona_anterior.pk) != (item.zona and item.zona.pk):
        HistorialTraslado.objects.create(item_inventario=item, zona_origen=zona_anterior, zona_destino=item.zona,
                                         usuario=usuario, observacion='Cambio de zona desde la edición de la factura')
    _guardar_telas(item, prod, reemplazar=True)


class FacturaProveedorListSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.ReadOnlyField(source='proveedor.nombre_empresa')

    class Meta:
        model = FacturaProveedor
        fields = [
            'id', 'id_manual', 'valor', 'fecha_factura', 'fecha_pago',
            'estado', 'proveedor', 'proveedor_nombre', 'observaciones',
            # fecha_pago = límite acordado; fecha_pago_real = cuando quedó pagada (D10f).
            'fecha_pago_real',
        ]

class AjusteFacturaSerializer(serializers.ModelSerializer):
    """Adicional de la factura: concepto, si suma o resta y el valor en pesos enteros (2026-10-28)."""
    concepto = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=False)
    valor = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('1'), max_value=Decimal('9999999999'))

    class Meta:
        model = AjusteFactura
        fields = ['id', 'concepto', 'tipo', 'valor']
        read_only_fields = ['id']

    def validate_valor(self, valor):
        if valor != valor.to_integral_value():
            raise serializers.ValidationError('Usa pesos enteros, sin centavos.')
        return valor


class FacturaProveedorSerializer(serializers.ModelSerializer):
    # Adicionales (suman o restan al total); al editar, la lista enviada reemplaza la anterior.
    ajustes = AjusteFacturaSerializer(many=True, required=False)
    # Write-only: lista de productos (cada uno validado con ProductoFacturaSerializer)
    productos = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
    )
    # Read-only: items del inventario vinculados a esta factura
    items_inventario = FacturasInventarioReadSerializer(many=True, read_only=True)
    detalles = DetalleFacturaSerializer(many=True, read_only=True)
    proveedor_nombre = serializers.ReadOnlyField(source='proveedor.nombre_empresa')
    comprobante_egreso = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = FacturaProveedor
        fields = [
            'id', 'id_manual', 'valor', 'fecha_factura', 'fecha_pago',
            'estado', 'proveedor', 'proveedor_nombre', 'observaciones',
            'productos',        # write-only (entrada)
            'items_inventario', # read-only (salida)
            'detalles',         # read-only fallback (salida histórica)
            'comprobante_egreso', # read-only (salida) - vínculo con el comprobante de egreso, si tiene
            'fecha_pago_real',  # read-only: lo fija el flujo de egresos (D10f)
            'ajustes',
        ]

    def validate_valor(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('El valor de la factura no puede ser negativo.')
        return value

    def validate(self, attrs):
        # Una factura ya vinculada a un comprobante de egreso no se puede editar:
        # su estado (pago_en_proceso/pagada) es gestionado por el flujo de comprobantes,
        # y permitir la edición aquí dejaría el comprobante desincronizado de la factura.
        if self.instance is not None and self.instance.comprobante_egreso_id is not None:
            raise serializers.ValidationError(
                'Esta factura está vinculada al comprobante de egreso '
                f'#{self.instance.comprobante_egreso_id} y no puede editarse. '
                'Para corregirla, primero gestiona el comprobante de egreso asociado.'
            )
        proveedor = attrs.get('proveedor', getattr(self.instance, 'proveedor', None))
        crudos = attrs.get('productos')
        ajustes = attrs.get('ajustes')
        if ajustes is None and self.instance is not None:
            ajustes = [{'tipo': a.tipo, 'valor': a.valor} for a in self.instance.ajustes.all()]
        neto_ajustes = sum((a['valor'] if a['tipo'] == AjusteFactura.SUMA else -a['valor'] for a in ajustes or []), Decimal(0))
        if crudos is None:
            if self.instance is None:
                attrs['productos'] = []
            return attrs

        # Toda fila inválida rechaza la factura completa con su error (U03).
        productos, errores = [], {}
        for i, crudo in enumerate(crudos, start=1):
            ps = ProductoFacturaSerializer(data=crudo, context={'proveedor': proveedor})
            if ps.is_valid():
                productos.append(ps.validated_data)
            else:
                errores[f'producto_{i}'] = ps.errors
        if errores:
            raise serializers.ValidationError({'productos': errores})

        # Ecuación del total (la misma que aplica el formulario): Σ costo × cantidad
        # de las filas + costo de las unidades entregadas que el formulario no envía.
        bloqueados = 0
        enviados = {pk for p in productos for pk in p['id_referencias']}
        if self.instance is not None:
            bloqueados = sum(i.costo_especifico for i in self.instance.items_inventario.filter(disponibilidad='entregado').exclude(pk__in=enviados))
        total = sum(p['costo'] * p['cantidad'] for p in productos) + bloqueados + neto_ajustes
        valor = attrs.get('valor', getattr(self.instance, 'valor', None))
        if productos and valor is not None and total != valor:
            detalle = ' con los adicionales' if neto_ajustes else ''
            raise serializers.ValidationError({'valor': f'La suma de los productos{detalle} ({total:,.0f}) no coincide con el valor de la factura ({valor:,.0f}).'})
        attrs['productos'] = productos
        return attrs

    def _usuario(self):
        request = self.context.get('request')
        return request.user if request is not None and request.user.is_authenticated else None

    @staticmethod
    def _lineas_de(productos):
        return [p['detalle_pedido'].pk for p in productos if p.get('detalle_pedido')]

    @staticmethod
    def _guardar_ajustes(factura, ajustes):
        if ajustes is None:
            return
        factura.ajustes.all().delete()
        AjusteFactura.objects.bulk_create([AjusteFactura(factura=factura, orden=i, **a) for i, a in enumerate(ajustes)])

    @transaction.atomic
    def create(self, validated_data):
        productos = validated_data.pop('productos', [])
        ajustes = validated_data.pop('ajustes', None)
        # Líneas de pedido bloqueadas antes de crear unidades (P11-01).
        lineas = recepcion.bloquear_lineas(self._lineas_de(productos))
        factura = FacturaProveedor.objects.create(**validated_data)
        self._guardar_ajustes(factura, ajustes)
        for prod in productos:
            if prod['id_referencias']:
                raise serializers.ValidationError({'productos': 'Una factura nueva no puede reutilizar unidades existentes.'})
            _crear_unidades(prod, factura, prod['cantidad'], self._usuario())
        recepcion.verificar_topes(lineas, factura)
        recepcion.actualizar_ordenes(lineas, self._usuario())
        return factura

    @transaction.atomic
    def update(self, instance, validated_data):
        productos = validated_data.pop('productos', None)
        ajustes = validated_data.pop('ajustes', None)
        lineas = {}
        if productos is not None:
            lineas = recepcion.bloquear_lineas(self._lineas_de(productos) + list(recepcion.lineas_de_unidades(instance)))

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        self._guardar_ajustes(instance, ajustes)
        if instance.id_manual is not None:
            instance.items_inventario.update(factura_manual=instance.id_manual or '')

        if productos is not None:
            self._sincronizar_productos(instance, productos)
            recepcion.verificar_topes(lineas, instance)
            recepcion.actualizar_ordenes(lineas, self._usuario())
        return instance

    def _sincronizar_productos(self, factura, productos):
        """Altas, cambios y bajas por identificador estable: una unidad existente
        conserva su PK, QR, historial, telas y vínculos (H04). Las entregadas que
        el formulario no envía se conservan intactas."""
        request = self.context.get('request')
        usuario = request.user if request is not None and request.user.is_authenticated else None
        existentes = {i.pk: i for i in Inventario.objects.select_for_update().filter(factura=factura).order_by('pk')}
        usados = set()
        for prod in productos:
            for pk in prod['id_referencias']:
                if pk not in existentes or pk in usados:
                    raise serializers.ValidationError({'productos': f'El producto {pk} no pertenece a esta factura.'})
                usados.add(pk)
                _actualizar_unidad(existentes[pk], prod, usuario)
            faltan = prod['cantidad'] - len(prod['id_referencias'])
            if faltan > 0:
                _crear_unidades(prod, factura, faltan, usuario)

        for pk, item in existentes.items():
            if pk in usados or item.disponibilidad == 'entregado':
                continue
            motivo = unidad_protegida(item)
            if motivo:
                raise serializers.ValidationError({'productos': f'No se puede quitar el producto {pk}: {motivo}.'})
            item.telas_cueros.all().delete()
            item.delete()


# ---------------------------------------------------------------------------
# RemisionSuministro
# ---------------------------------------------------------------------------

# Estados de remisión que "retienen" sus productos: mientras la remisión esté en uno de
# estos estados, sus ítems de inventario no pueden ir en otra remisión.
REMISION_ESTADOS_ACTIVOS = ('creada', 'despachada')
# Estados que cuentan como "ya remisionado/entregado" (todo menos anulada/devuelta).
REMISION_ESTADOS_VIGENTES = ('creada', 'despachada', 'finalizada')


# Qué estado puede seguir a cuál. Finalizada, devuelta y anulada son definitivos.
REMISION_TRANSICIONES = {
    'creada': {'despachada', 'finalizada', 'anulada'},
    'despachada': {'finalizada', 'devuelta', 'creada'},
    'finalizada': set(),
    'devuelta': set(),
    'anulada': set(),
}


def tiene_permiso(request, codigo):
    """Permiso dinámico del rol (el administrador siempre lo tiene)."""
    if request is None or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return False
    return check_feature_permission(codigo)().has_permission(request, None)


def ventas_remisionables_para(request):
    """Ventas sin entregar que el usuario puede remisionar: todas con
    CREAR_REMISION_TODAS_VENTAS; si no, solo sus ventas propias o compartidas."""
    qs = Venta.objects.filter(estado='pendiente')
    if not tiene_permiso(request, 'CREAR_REMISION_TODAS_VENTAS'):
        user = request.user
        qs = qs.filter(Q(vendedor=user) | Q(vendedores_compartidos=user)).distinct()
    return qs


def items_retenidos_por_remision(item_ids, excluir_remision_id=None):
    """{id_referencia: id de la remisión activa que ya lo tiene} para los ítems dados."""
    through = RemisionSuministro.inventario_items.through.objects.filter(
        inventario_id__in=list(item_ids),
        remisionsuministro__estado__in=REMISION_ESTADOS_ACTIVOS,
    )
    if excluir_remision_id:
        through = through.exclude(remisionsuministro_id=excluir_remision_id)
    return dict(through.values_list('inventario_id', 'remisionsuministro_id'))


class RemisionItemManualSerializer(serializers.ModelSerializer):
    # Al editar una remisión: con `id` se actualiza esa línea, sin `id` se crea una nueva.
    id = serializers.IntegerField(required=False)
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model = RemisionItemManual
        fields = [
            'id', 'categoria', 'categoria_nombre', 'subcategoria', 'subcategoria_nombre',
            'referencia', 'descripcion', 'tela', 'cantidad', 'venta', 'detalle_pedido',
        ]
        extra_kwargs = {
            'categoria': {'required': False, 'allow_null': True},
            'subcategoria': {'required': False, 'allow_null': True},
            'referencia': {'required': False, 'allow_blank': True},
            'descripcion': {'required': False, 'allow_blank': True},
            'tela': {'required': False, 'allow_blank': True},
            'venta': {'required': False, 'allow_null': True},
            'detalle_pedido': {'required': False, 'allow_null': True},
        }

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else ''

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else ''

    def validate_cantidad(self, value):
        if value < 1:
            raise serializers.ValidationError('La cantidad debe ser al menos 1.')
        return value

    def validate(self, attrs):
        attrs['referencia'] = (attrs.get('referencia') or '').strip()
        attrs['descripcion'] = (attrs.get('descripcion') or '').strip()
        attrs['tela'] = (attrs.get('tela') or '').strip()
        categoria = attrs.get('categoria')
        subcategoria = attrs.get('subcategoria')
        if subcategoria and categoria and subcategoria.categoria_id != categoria.id:
            raise serializers.ValidationError({
                'subcategoria': f'"{subcategoria.nombre}" no pertenece a la categoría {categoria.nombre}.'
            })
        if subcategoria and not categoria:
            attrs['categoria'] = subcategoria.categoria
        if not (attrs['referencia'] or attrs['descripcion'] or subcategoria):
            raise serializers.ValidationError(
                'Indica al menos la referencia, la subcategoría o la descripción de cada producto.'
            )
        return attrs


class RemisionSuministroSerializer(serializers.ModelSerializer):
    inventario_items = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Inventario.objects.all(),
        required=False
    )
    ventas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Venta.objects.all(),
        required=False
    )
    items_manuales = RemisionItemManualSerializer(many=True, required=False)
    # {id_referencia: texto}: descripción para el cliente de productos de inventario,
    # solo en esta remisión (el inventario no cambia). Se lee en inventario_items_detalle.
    descripciones_inventario = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        write_only=True,
    )
    # {id_referencia: tapizado} de productos de inventario (material, referencia, color).
    telas_inventario = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=200),
        required=False,
        write_only=True,
    )
    vendedor_nombre = serializers.SerializerMethodField()
    transportador_usuario_nombre = serializers.ReadOnlyField(source='transportador_usuario.first_name')
    creado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = RemisionSuministro
        fields = [
            'id', 'fecha_creacion', 'fecha_entrega', 'hora_desde', 'hora_hasta',
            'direccion_entrega', 'ciudad', 'barrio', 'orden_asociada', 'ventas', 'estado',
            'sin_saldo', 'saldo', 'metodo_pago', 'transportador_usuario', 'transportador_usuario_nombre',
            'transportador', 'vendedor', 'vendedor_nombre', 'observacion', 'novedades',
            'cliente_nombre', 'cliente_documento', 'cliente_telefono1', 'cliente_telefono2',
            'inventario_items', 'items_manuales', 'descripciones_inventario', 'telas_inventario',
            'nota_transportador', 'costo_entrega', 'creado_por', 'creado_por_nombre',
        ]
        read_only_fields = ['creado_por']

    def get_creado_por_nombre(self, obj):
        u = obj.creado_por
        return (u.first_name or u.username) if u else None

    def get_vendedor_nombre(self, obj):
        u = obj.vendedor
        return (u.first_name or u.username) if u else None

    def validate(self, attrs):
        if self.instance is not None:
            return self._validar_edicion(attrs)

        request = self.context.get('request')

        ventas = list(attrs.get('ventas') or [])
        orden = attrs.get('orden_asociada')
        if orden and orden not in ventas:
            ventas.insert(0, orden)
        attrs['ventas'] = ventas
        if ventas and not orden:
            attrs['orden_asociada'] = ventas[0]

        for venta in ventas:
            if venta.estado == 'entregado':
                raise serializers.ValidationError({'ventas': f'La venta {venta.id} ya fue entregada; no se le pueden crear más remisiones.'})
            if venta.estado == 'anulada':
                raise serializers.ValidationError({'ventas': f'La venta {venta.id} está anulada.'})
        if request is not None and not ventas and not tiene_permiso(request, 'CREAR_REMISION_TODAS_VENTAS'):
            raise serializers.ValidationError({'ventas': 'Elige la venta que vas a entregar.'})
        if request is not None and ventas:
            permitidas = set(ventas_remisionables_para(request).filter(id__in=[v.id for v in ventas]).values_list('id', flat=True))
            ajenas = [str(v.id) for v in ventas if v.id not in permitidas]
            if ajenas:
                raise serializers.ValidationError({'ventas': f'Solo puedes remisionar tus ventas propias o compartidas ({", ".join(ajenas)}).'})

        if not attrs.get('fecha_entrega'):
            raise serializers.ValidationError({'fecha_entrega': 'Indica la fecha de entrega.'})
        self._validar_horas(attrs.get('hora_desde'), attrs.get('hora_hasta'))

        items = attrs.get('inventario_items') or []
        manuales = attrs.get('items_manuales') or []
        if not items and not manuales:
            raise serializers.ValidationError({'productos': 'Agrega al menos un producto a entregar.'})

        if items and request is not None:
            self._validar_items_autorizados(request, items, ventas)
        if items:
            retenidos = items_retenidos_por_remision(i.pk for i in items)
            for item in items:
                if item.pk in retenidos:
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya está en la remisión #{retenidos[item.pk]}.'
                    })
                if item.disponibilidad in ('despachado', 'entregado', 'devuelto_proveedor'):
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya fue {item.get_disponibilidad_display().lower()}.'
                    })
        for campo in ('descripciones_inventario', 'telas_inventario'):
            if campo in attrs:
                attrs[campo] = self._limpiar_descripciones(attrs[campo], {i.pk for i in items}, campo)
        return attrs

    @staticmethod
    def _validar_items_autorizados(request, items, ventas):
        """Cada producto debe pertenecer a una de las ventas de la remisión, o
        ser stock libre (sin venta) disponible para asignar (H14)."""
        ids_ventas = {v.id for v in ventas}
        for item in items:
            venta_item = item.venta_id or (item.pedido.venta_id if item.pedido_id and item.pedido else None)
            if venta_item:
                if venta_item not in ids_ventas:
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} pertenece a la venta {venta_item}, que no está en esta remisión.'
                    })
            elif item.disponibilidad not in ('exhibicion', 'consignacion'):
                raise serializers.ValidationError({
                    'inventario_items': f'El producto {item.pk} no está disponible para asignar ({item.get_disponibilidad_display().lower()}).'
                })

    @staticmethod
    def _limpiar_descripciones(textos, ids_remision, campo='descripciones_inventario'):
        """Solo textos no vacíos de productos que van en la remisión."""
        ajenos = [k for k in textos if k not in ids_remision]
        if ajenos:
            raise serializers.ValidationError({
                campo: f'El producto {ajenos[0]} no está en la remisión.'
            })
        return {k: v.strip() for k, v in textos.items() if v.strip()}

    @staticmethod
    def _validar_horas(desde, hasta):
        if desde and hasta and hasta <= desde:
            raise serializers.ValidationError({'hora_hasta': 'La hora final debe ser posterior a la inicial.'})

    def _validar_edicion(self, attrs):
        inst = self.instance
        nuevo = attrs.get('estado', inst.estado)
        if nuevo != inst.estado and nuevo not in REMISION_TRANSICIONES.get(inst.estado, set()):
            etiquetas = dict(RemisionSuministro.ESTADO_CHOICES)
            raise serializers.ValidationError({
                'estado': f'Una remisión {etiquetas.get(inst.estado, inst.estado).lower()} no puede pasar a {etiquetas.get(nuevo, nuevo).lower()}.'
            })
        # Costo del flete y nota del transportador se pueden registrar incluso ya entregada;
        # el resto de datos (programación, cliente, cobro) solo mientras esté activa.
        campos_edicion = set(attrs) - {'estado', 'nota_transportador', 'costo_entrega', 'inventario_items', 'ventas'}
        if campos_edicion and inst.estado not in REMISION_ESTADOS_ACTIVOS:
            raise serializers.ValidationError(f'La remisión está {inst.get_estado_display().lower()}; ya no se puede editar.')
        if 'items_manuales' in attrs and not attrs['items_manuales'] and not inst.inventario_items.exists():
            raise serializers.ValidationError({'productos': 'La remisión debe quedar con al menos un producto.'})
        if 'fecha_entrega' in attrs and not attrs['fecha_entrega']:
            raise serializers.ValidationError({'fecha_entrega': 'Indica la fecha de entrega.'})
        self._validar_horas(attrs.get('hora_desde', inst.hora_desde), attrs.get('hora_hasta', inst.hora_hasta))
        ids = None
        for campo in ('descripciones_inventario', 'telas_inventario'):
            if campo in attrs:
                ids = ids if ids is not None else set(inst.inventario_items.values_list('pk', flat=True))
                attrs[campo] = self._limpiar_descripciones(attrs[campo], ids, campo)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        inventario_items_data = validated_data.pop('inventario_items', [])
        ventas_data = validated_data.pop('ventas', [])
        manuales_data = validated_data.pop('items_manuales', [])
        textos = validated_data.pop('descripciones_inventario', {})
        telas = validated_data.pop('telas_inventario', {})
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            validated_data['creado_por'] = request.user

        if inventario_items_data:
            # Comprobación repetida BAJO BLOQUEO (orden estable por PK): entre
            # validar y guardar otra remisión pudo reservar el mismo producto (H15).
            pks = sorted(i.pk for i in inventario_items_data)
            bloqueados = list(Inventario.objects.select_for_update().filter(pk__in=pks).order_by('pk'))
            retenidos = items_retenidos_por_remision(pks)
            for item in bloqueados:
                if item.pk in retenidos:
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya está en la remisión #{retenidos[item.pk]}.'
                    })
                if item.disponibilidad in ('despachado', 'entregado', 'devuelto_proveedor'):
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya no está disponible ({item.get_disponibilidad_display().lower()}).'
                    })

        remision = super().create(validated_data)
        if ventas_data:
            remision.ventas.set(ventas_data)
        if inventario_items_data:
            remision.inventario_items.set(inventario_items_data)
            movimientos.aplicar(bloqueados, 'reserva', request.user if request is not None else None,
                                documento=f'remision:{remision.pk}', disponibilidad='por_despachar')
        if manuales_data:
            RemisionItemManual.objects.bulk_create([
                RemisionItemManual(remision=remision, **{k: v for k, v in m.items() if k != 'id'})
                for m in manuales_data
            ])
        if textos or telas:
            self._guardar_descripciones(remision, textos, telas)
        return remision

    @transaction.atomic
    def update(self, instance, validated_data):
        # Las ventas y los productos de inventario se fijan al crear (mueven la
        # disponibilidad del inventario). Los productos escritos o de pedido sí se editan.
        validated_data.pop('inventario_items', None)
        validated_data.pop('ventas', None)
        manuales = validated_data.pop('items_manuales', None)
        textos = validated_data.pop('descripciones_inventario', None)
        telas = validated_data.pop('telas_inventario', None)
        instance = super().update(instance, validated_data)
        if manuales is not None:
            self._sincronizar_manuales(instance, manuales)
        if textos is not None or telas is not None:
            actuales = list(instance.textos_inventario.all())
            if textos is None:
                textos = {t.inventario_id: t.descripcion for t in actuales if t.descripcion}
            if telas is None:
                telas = {t.inventario_id: t.tela for t in actuales if t.tela}
            self._guardar_descripciones(instance, textos, telas)
        return instance

    @staticmethod
    def _guardar_descripciones(remision, textos, telas=None):
        """Deja exactamente estos textos y telas; los productos sin texto vuelven al del inventario."""
        telas = telas or {}
        RemisionInventarioTexto.objects.filter(remision=remision).delete()
        RemisionInventarioTexto.objects.bulk_create([
            RemisionInventarioTexto(remision=remision, inventario_id=pk, descripcion=textos.get(pk, ''), tela=telas.get(pk, ''))
            for pk in sorted(set(textos) | set(telas))
        ])
        getattr(remision, '_prefetched_objects_cache', {}).pop('textos_inventario', None)

    @staticmethod
    def _sincronizar_manuales(remision, manuales):
        """Deja la remisión con exactamente estas líneas: actualiza las que traen `id`,
        crea las nuevas y borra las que ya no vienen."""
        existentes = {m.id: m for m in RemisionItemManual.objects.filter(remision=remision)}
        conservar = set()
        nuevos = []
        for datos in manuales:
            datos = dict(datos)
            item = existentes.get(datos.pop('id', None))
            if item:
                for campo, valor in datos.items():
                    setattr(item, campo, valor)
                item.save()
                conservar.add(item.id)
            else:
                nuevos.append(RemisionItemManual(remision=remision, **datos))
        RemisionItemManual.objects.filter(remision=remision).exclude(id__in=conservar).delete()
        RemisionItemManual.objects.bulk_create(nuevos)
        getattr(remision, '_prefetched_objects_cache', {}).pop('items_manuales', None)

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        # Cliente: lo guardado en la remisión manda; las remisiones antiguas (sin esos
        # campos) siguen tomando el cliente de la venta principal.
        c = instance.orden_asociada.cliente if (instance.orden_asociada_id and instance.orden_asociada) else None
        representation['cliente_nombre'] = instance.cliente_nombre or (c.nombre if c else '') or 'Cliente Nuevo'
        representation['cliente_documento'] = instance.cliente_documento or (c.cedula if c else '') or ''
        representation['cliente_telefono1'] = instance.cliente_telefono1 or (c.telefono1 if c else '') or ''
        representation['cliente_telefono2'] = instance.cliente_telefono2 or (c.telefono2 if c else '') or ''

        # inventario_items_detalle: solo usamos campos ya en el objeto prefetcheado.
        # Usamos el prefetch_cache si existe (puesto por el viewset), sin llamadas extra.
        items_data = []
        prefetched = getattr(instance, '_prefetched_objects_cache', {}).get('inventario_items', None)
        items_qs = prefetched if prefetched is not None else instance.inventario_items.select_related(
            'referencia', 'referencia__proveedor', 'categoria', 'subcategoria'
        ).all()
        filas_texto = list(instance.textos_inventario.all())
        textos = {t.inventario_id: t.descripcion for t in filas_texto}
        telas = {t.inventario_id: t.tela for t in filas_texto}
        for item in items_qs:
            ref = item.referencia
            items_data.append({
                'id_referencia': item.id_referencia,
                # Para verificar con el QR la carga y la entrega (P11-05).
                'qr_uuid': str(item.qr_uuid) if item.qr_uuid else None,
                'producto_nombre': ref.nombre if ref else '',
                'variacion': item.variacion or '',
                'observacion': item.observacion or '',
                'descripcion_remision': textos.get(item.id_referencia, ''),
                'tela_remision': telas.get(item.id_referencia, ''),
                'categoria_nombre': item.categoria.nombre if item.categoria else '',
                'subcategoria_nombre': item.subcategoria.nombre if item.subcategoria else '',
                'proveedor_nombre': (ref.proveedor.nombre_empresa if ref and ref.proveedor else ''),
                'imagen': item.imagen,
                'grupo_id': item.grupo.id if item.grupo else None,
                'grupo_nombre': item.grupo.nombre if item.grupo else '',
                'grupo_observacion': item.grupo.observacion if item.grupo else '',
            })
        representation['inventario_items_detalle'] = items_data

        representation['ventas_detalle'] = [
            {'id': v.id, 'estado': v.estado} for v in sorted(instance.ventas.all(), key=lambda v: v.id)
        ]
        representation['eventos'] = [
            {
                'tipo': e.tipo,
                'tipo_label': e.get_tipo_display(),
                'detalle': e.detalle,
                'fecha': e.fecha,
                'usuario_nombre': (e.usuario.first_name or e.usuario.username) if e.usuario else None,
            }
            for e in instance.eventos.all()
        ]
        # Lo que no se entregó al confirmar (P11-03).
        representation['no_entregados'] = [
            {
                'inventario': n.inventario_id,
                'item_manual': n.item_manual_id,
                'cantidad': n.cantidad,
                'motivo': n.motivo,
                'motivo_label': n.get_motivo_display(),
                'detalle': n.detalle,
            }
            for n in instance.novedades_entrega.all()
        ]

        request = self.context.get('request')
        if request is not None and getattr(request.user, 'role', None) != 'transportador' \
                and not tiene_permiso(request, 'VER_COSTO_ENTREGA_REMISION'):
            representation.pop('costo_entrega', None)
        return representation
