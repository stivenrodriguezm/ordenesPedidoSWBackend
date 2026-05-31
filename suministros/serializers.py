import random
from rest_framework import serializers
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro,
    GrupoInventario, GrupoInventarioComponente
)
from ordenes.models import Venta, Referencia


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

    class Meta:
        model = GrupoInventario
        fields = [
            'id', 'nombre', 'descripcion', 'activo', 'componentes', 
            'items_count', 'costo_total', 'subcategoria_id', 'subcategoria_nombre', 'observacion'
        ]

    def get_items_count(self, obj):
        return obj.items_inventario.count()

    def get_costo_total(self, obj):
        return sum(item.costo_especifico for item in obj.items_inventario.all())

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
# Inventario (tabla principal)
# ---------------------------------------------------------------------------

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

    class Meta:
        model = Inventario
        fields = '__all__'
        extra_fields = ['producto_nombre', 'categoria_id', 'categoria_nombre',
                        'subcategoria_nombre', 'proveedor_id', 'proveedor_nombre',
                        'factura_id_manual', 'factura_id', 'venta_numero',
                        'grupo_id', 'grupo_nombre']

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


# ---------------------------------------------------------------------------
# Nested read-only serializer: items del inventario dentro de una factura
# ---------------------------------------------------------------------------

class FacturasInventarioReadSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()
    venta_id = serializers.SerializerMethodField()

    class Meta:
        model = Inventario
        fields = [
            'id_referencia', 'referencia', 'referencia_nombre',
            'categoria', 'categoria_nombre',
            'subcategoria', 'subcategoria_nombre',
            'variacion', 'costo_especifico', 'observacion',
            'disponibilidad', 'venta', 'venta_id', 'imagen', 'fecha_ingreso',
        ]

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else None

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else None

    def get_venta_id(self, obj):
        return str(obj.venta.id) if obj.venta else None


# ---------------------------------------------------------------------------
# DetalleFactura (kept for backward compatibility with existing records)
# ---------------------------------------------------------------------------

class DetalleFacturaSerializer(serializers.ModelSerializer):
    referencia_nombre = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model = DetalleFactura
        fields = '__all__'
        read_only_fields = ('factura',)

    def get_referencia_nombre(self, obj):
        return obj.referencia.nombre if obj.referencia else None

    def get_categoria_nombre(self, obj):
        return obj.categoria.nombre if obj.categoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else None


# ---------------------------------------------------------------------------
# Helper: create one Inventario item from a product dict
# ---------------------------------------------------------------------------

def _crear_item_inventario(prod_data, factura):
    """
    Crea uno o más items de Inventario desde los datos del producto
    recibido en el form de Nueva Factura. No usa DetalleFactura.
    Soporta 'cantidad' (crea N unidades) y 'grupo_id' (asigna al grupo).
    """
    ref_id = prod_data.get('referencia')
    cat_id = prod_data.get('categoria')
    subcat_id = prod_data.get('subcategoria')
    venta_id_str = str(prod_data.get('venta_id') or '')
    grupo_id = prod_data.get('grupo_id') or prod_data.get('grupo')
    cantidad = int(prod_data.get('cantidad') or 1)
    if cantidad < 1:
        cantidad = 1

    referencia = Referencia.objects.filter(id=ref_id).first() if ref_id else None
    categoria = Categoria.objects.filter(id=cat_id).first() if cat_id else None
    subcategoria = Subcategoria.objects.filter(id=subcat_id).first() if subcat_id else None
    venta = Venta.objects.filter(id=venta_id_str).first() if venta_id_str.isdigit() else None

    # Resolver grupo (puede ser id numérico o None)
    grupo = None
    if grupo_id:
        try:
            grupo = GrupoInventario.objects.filter(id=int(grupo_id)).first()
        except (ValueError, TypeError):
            grupo = None

    prefix = (categoria.nombre[:2].upper() if categoria else 'XX')

    for _ in range(cantidad):
        gen_id = f"{prefix}{random.randint(1000, 9999)}"
        while Inventario.objects.filter(id_referencia=gen_id).exists():
            gen_id = f"{prefix}{random.randint(1000, 9999)}"

        Inventario.objects.create(
            id_referencia=gen_id,
            referencia=referencia,
            categoria=categoria,
            subcategoria=subcategoria,
            variacion=prod_data.get('variacion', ''),
            costo_especifico=prod_data.get('costo', 0),
            observacion=prod_data.get('observacion') or '',
            disponibilidad=prod_data.get('disponibilidad') or 'exhibicion',
            venta=venta,
            factura=factura,
            factura_manual=factura.id_manual,
            imagen=prod_data.get('imagen') or None,
            grupo=grupo,
        )


# ---------------------------------------------------------------------------
# FacturaProveedor
# ---------------------------------------------------------------------------

class FacturaProveedorSerializer(serializers.ModelSerializer):
    # Write-only: lista de productos recibidos al crear la factura
    productos = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        default=list,
    )
    # Read-only: items del inventario vinculados a esta factura
    items_inventario = FacturasInventarioReadSerializer(many=True, read_only=True)
    proveedor_nombre = serializers.ReadOnlyField(source='proveedor.nombre_empresa')

    class Meta:
        model = FacturaProveedor
        fields = [
            'id', 'id_manual', 'valor', 'fecha_factura', 'fecha_pago',
            'estado', 'proveedor', 'proveedor_nombre', 'observaciones',
            'productos',        # write-only (entrada)
            'items_inventario', # read-only (salida)
        ]

    def create(self, validated_data):
        productos_data = validated_data.pop('productos', [])
        factura = FacturaProveedor.objects.create(**validated_data)
        for prod_data in productos_data:
            _crear_item_inventario(prod_data, factura)
        return factura

    def update(self, instance, validated_data):
        productos_data = validated_data.pop('productos', None)

        # Actualizar campos de la factura
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Si se envían productos en el update: reemplazar los items de inventario
        if productos_data is not None:
            # Eliminar items del inventario vinculados a esta factura
            instance.items_inventario.all().delete()
            for prod_data in productos_data:
                _crear_item_inventario(prod_data, instance)

        return instance


# ---------------------------------------------------------------------------
# RemisionSuministro
# ---------------------------------------------------------------------------

class RemisionSuministroSerializer(serializers.ModelSerializer):
    inventario_items = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Inventario.objects.all(),
        required=False
    )
    vendedor_nombre = serializers.ReadOnlyField(source='vendedor.username')
    transportador_usuario_nombre = serializers.ReadOnlyField(source='transportador_usuario.first_name')

    class Meta:
        model = RemisionSuministro
        fields = [
            'id', 'fecha_creacion', 'fecha_entrega', 'hora_desde', 'hora_hasta',
            'direccion_entrega', 'ciudad', 'barrio', 'orden_asociada', 'estado',
            'sin_saldo', 'saldo', 'metodo_pago', 'transportador_usuario', 'transportador_usuario_nombre',
            'transportador', 'vendedor', 'vendedor_nombre', 'observacion',
            'inventario_items', 'nota_transportador', 'costo_entrega'
        ]

    def create(self, validated_data):
        inventario_items_data = validated_data.pop('inventario_items', [])
        remision = super().create(validated_data)
        if inventario_items_data:
            remision.inventario_items.set(inventario_items_data)
            # Marcar el inventario como "Por despachar"
            for item in inventario_items_data:
                item.disponibilidad = 'por_despachar'
                item.save()
        return remision

    def update(self, instance, validated_data):
        validated_data.pop('inventario_items', None)  # no permitir cambiar items en PATCH
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        
        # Obtener el nombre del cliente desde la orden asociada
        if instance.orden_asociada and instance.orden_asociada.cliente:
            representation['cliente_nombre'] = instance.orden_asociada.cliente.nombre
            representation['cliente_documento'] = instance.orden_asociada.cliente.cedula
            representation['cliente_telefono1'] = instance.orden_asociada.cliente.telefono1
            representation['cliente_telefono2'] = instance.orden_asociada.cliente.telefono2
        else:
            representation['cliente_nombre'] = 'Cliente Nuevo'
            representation['cliente_documento'] = ''
            representation['cliente_telefono1'] = ''
            representation['cliente_telefono2'] = ''
            
        items_data = []
        for item in instance.inventario_items.all():
            items_data.append({
                'id_referencia': item.id_referencia,
                'producto_nombre': getattr(item.referencia, 'nombre', ''),
                'variacion': item.variacion,
                'observacion': item.observacion,
                'categoria_nombre': item.categoria.nombre if item.categoria else (item.referencia.categorias.first().nombre if item.referencia and item.referencia.categorias.exists() else ''),
                'subcategoria_nombre': item.subcategoria.nombre if item.subcategoria else '',
                'proveedor_nombre': item.referencia.proveedor.nombre_empresa if item.referencia and item.referencia.proveedor else '',
                'imagen': item.imagen,
            })
        representation['inventario_items_detalle'] = items_data
        return representation
