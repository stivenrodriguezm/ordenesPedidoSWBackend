import random
from django.db import transaction
from rest_framework import serializers
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro,
    GrupoInventario, GrupoInventarioComponente,
    Sede, Zona, HistorialTraslado, CostoAdicionalInventario,
    ItemInventarioTelaCuero
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
        try:
            base = float(obj.costo_especifico or 0)
            tela = 0
            if getattr(obj, 'lleva_tela', False):
                tela = float(obj.tela_costo_metro or 0) * float(obj.tela_cantidad_metros or 0)
            adicionales = 0
            try:
                adicionales = sum(float(c.valor) for c in obj.costos_adicionales.all())
            except Exception:
                pass
            return round(base + tela + adicionales, 2)
        except Exception:
            return 0.0

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

    class Meta:
        model = Inventario
        fields = [
            'id_referencia', 'referencia', 'referencia_nombre',
            'categoria', 'categoria_nombre',
            'subcategoria', 'subcategoria_nombre',
            'variacion', 'costo_especifico', 'observacion',
            'disponibilidad', 'estado_fisico', 'venta', 'venta_id', 'imagen', 'fecha_ingreso', 'grupo_nombre', 'grupo_id',
            'grupo_categoria_nombre', 'grupo_subcategoria_nombre',
            'lleva_tela', 'tela_referencia', 'tela_color', 'tela_costo_metro', 'tela_cantidad_metros', 'vendedor_nombre'
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
# Helper: create one Inventario item from a product dict
# ---------------------------------------------------------------------------

def _crear_item_inventario(prod_data, factura):
    """
    Crea uno o más items de Inventario desde los datos del producto
    recibido en el form de Nueva o Editar Factura. No usa DetalleFactura.
    Soporta 'cantidad' (crea N unidades) y 'grupo_id' (asigna al grupo).
    """
    ref_id = prod_data.get('referencia')
    cat_id = prod_data.get('categoria')
    subcat_id = prod_data.get('subcategoria')
    venta_id_str = str(prod_data.get('venta_id') or prod_data.get('venta') or '')
    grupo_id = prod_data.get('grupo_id') or prod_data.get('grupo')

    try:
        cantidad = int(prod_data.get('cantidad') or 1)
    except (ValueError, TypeError):
        cantidad = 1
    if cantidad < 1:
        cantidad = 1

    referencia = Referencia.objects.filter(id=ref_id).first() if ref_id else None
    if not referencia:
        return

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

    try:
        costo_spec = float(prod_data.get('costo') or 0)
    except (ValueError, TypeError):
        costo_spec = 0.0

    raw_zona = prod_data.get('zona') or prod_data.get('zona_id')
    try:
        zona_id = int(raw_zona) if raw_zona else None
    except (ValueError, TypeError):
        zona_id = None

    tela_ref = str(prod_data.get('tela_referencia') or prod_data.get('telaReferencia') or '').strip()
    tela_col = str(prod_data.get('tela_color') or prod_data.get('telaColor') or '').strip()

    try:
        tela_costo = float(prod_data.get('tela_costo_metro') or prod_data.get('telaCostoMetro') or 0)
    except (ValueError, TypeError):
        tela_costo = 0.0

    try:
        tela_cant = float(prod_data.get('tela_cantidad_metros') or prod_data.get('telaCantidadMetros') or 0)
    except (ValueError, TypeError):
        tela_cant = 0.0

    lleva_tela = bool(prod_data.get('lleva_tela')) or bool(tela_ref) or bool(tela_col) or bool(tela_costo > 0)
    prefix = (categoria.nombre[:2].upper() if (categoria and getattr(categoria, 'nombre', None)) else 'XX')

    for _ in range(cantidad):
        gen_id = f"{prefix}{random.randint(1000, 9999)}"
        while Inventario.objects.filter(id_referencia=gen_id).exists():
            gen_id = f"{prefix}{random.randint(1000, 9999)}"

        inv_item = Inventario.objects.create(
            id_referencia=gen_id,
            referencia=referencia,
            categoria=categoria,
            subcategoria=subcategoria,
            variacion=str(prod_data.get('variacion') or ''),
            costo_especifico=costo_spec,
            observacion=str(prod_data.get('observacion') or ''),
            disponibilidad=str(prod_data.get('disponibilidad') or 'exhibicion'),
            estado_fisico=str(prod_data.get('estado_fisico') or 'buen_estado'),
            zona_id=zona_id,
            venta=venta,
            factura=factura,
            factura_manual=factura.id_manual if (factura and getattr(factura, 'id_manual', None)) else '',
            imagen=prod_data.get('imagen') or None,
            grupo=grupo,
            lleva_tela=lleva_tela,
            tela_referencia=tela_ref if tela_ref else None,
            tela_color=tela_col if tela_col else None,
            tela_costo_metro=tela_costo,
            tela_cantidad_metros=tela_cant,
        )

        telas_cueros_list = prod_data.get('telas_cueros') or prod_data.get('telasCueros') or []
        if isinstance(telas_cueros_list, list) and len(telas_cueros_list) > 0:
            for tc in telas_cueros_list:
                if isinstance(tc, dict):
                    ItemInventarioTelaCuero.objects.create(
                        inventario=inv_item,
                        tipo=str(tc.get('tipo') or 'tela'),
                        referencia=str(tc.get('referencia') or '').strip(),
                        color=str(tc.get('color') or '').strip(),
                        unidad_medida=str(tc.get('unidad_medida') or ('metro' if tc.get('tipo') == 'tela' else 'decimetro')),
                        costo_unidad=float(tc.get('costo_unidad') or tc.get('costoUnidad') or 0),
                        cantidad=float(tc.get('cantidad') or 0),
                    )
        elif lleva_tela and (tela_ref or tela_col or tela_costo > 0):
            ItemInventarioTelaCuero.objects.create(
                inventario=inv_item,
                tipo='tela',
                referencia=tela_ref,
                color=tela_col,
                unidad_medida='metro',
                costo_unidad=tela_costo,
                cantidad=tela_cant,
            )


def _actualizar_item_inventario(inv_item, prod_data, factura):
    """Actualiza los parámetros de un ítem de inventario existente sin recrearlo."""
    if not inv_item:
        return

    if 'variacion' in prod_data:
        inv_item.variacion = str(prod_data.get('variacion') or '')
    if 'costo' in prod_data or 'costo_especifico' in prod_data:
        try:
            inv_item.costo_especifico = float(prod_data.get('costo') or prod_data.get('costo_especifico') or 0)
        except (ValueError, TypeError):
            pass
    if 'observacion' in prod_data:
        inv_item.observacion = str(prod_data.get('observacion') or '')
    if 'disponibilidad' in prod_data:
        inv_item.disponibilidad = str(prod_data.get('disponibilidad') or inv_item.disponibilidad)
    if 'estado_fisico' in prod_data:
        inv_item.estado_fisico = str(prod_data.get('estado_fisico') or inv_item.estado_fisico)

    raw_zona = prod_data.get('zona') or prod_data.get('zona_id')
    if raw_zona is not None:
        try:
            inv_item.zona_id = int(raw_zona) if raw_zona else None
        except (ValueError, TypeError):
            pass

    grupo_id = prod_data.get('grupo_id') or prod_data.get('grupo')
    if grupo_id is not None:
        try:
            inv_item.grupo_id = int(grupo_id) if grupo_id else None
        except (ValueError, TypeError):
            pass

    if factura and getattr(factura, 'id_manual', None):
        inv_item.factura_manual = factura.id_manual

    telas_cueros_list = prod_data.get('telas_cueros') or prod_data.get('telasCueros')
    if isinstance(telas_cueros_list, list):
        inv_item.telas_cueros.all().delete()
        for tc in telas_cueros_list:
            if isinstance(tc, dict) and (tc.get('referencia') or tc.get('color') or tc.get('cantidad')):
                ItemInventarioTelaCuero.objects.create(
                    inventario=inv_item,
                    tipo=str(tc.get('tipo') or 'tela'),
                    referencia=str(tc.get('referencia') or '').strip(),
                    color=str(tc.get('color') or '').strip(),
                    unidad_medida=str(tc.get('unidad_medida') or ('metro' if tc.get('tipo') == 'tela' else 'decimetro')),
                    costo_unidad=float(tc.get('costo_unidad') or tc.get('costoUnidad') or 0),
                    cantidad=float(tc.get('cantidad') or 0),
                )

    inv_item.save()


# ---------------------------------------------------------------------------
# FacturaProveedor
# ---------------------------------------------------------------------------

class FacturaProveedorListSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.ReadOnlyField(source='proveedor.nombre_empresa')

    class Meta:
        model = FacturaProveedor
        fields = [
            'id', 'id_manual', 'valor', 'fecha_factura', 'fecha_pago',
            'estado', 'proveedor', 'proveedor_nombre', 'observaciones'
        ]

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
    detalles = DetalleFacturaSerializer(many=True, read_only=True)
    proveedor_nombre = serializers.ReadOnlyField(source='proveedor.nombre_empresa')

    class Meta:
        model = FacturaProveedor
        fields = [
            'id', 'id_manual', 'valor', 'fecha_factura', 'fecha_pago',
            'estado', 'proveedor', 'proveedor_nombre', 'observaciones',
            'productos',        # write-only (entrada)
            'items_inventario', # read-only (salida)
            'detalles',         # read-only fallback (salida histórica)
        ]

    @transaction.atomic
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

        # Si se actualizó el id_manual, actualizarlo en los items de inventario vinculados
        if instance.id_manual is not None:
            instance.items_inventario.update(factura_manual=instance.id_manual or '')

        # Si se envían productos en el update: actualizar sus ítems existentes
        if productos_data is not None and len(productos_data) > 0:
            items_existentes = list(instance.items_inventario.all())
            if len(items_existentes) > 0:
                for i, prod_data in enumerate(productos_data):
                    if i < len(items_existentes):
                        _actualizar_item_inventario(items_existentes[i], prod_data, instance)
                    else:
                        _crear_item_inventario(prod_data, instance)
            else:
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
            # La disponibilidad ('por_despachar') la actualiza perform_create del viewset en bulk
        return remision

    def update(self, instance, validated_data):
        validated_data.pop('inventario_items', None)  # no permitir cambiar items en PATCH
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        # Cliente — ya traído por select_related en el viewset, sin queries extra
        if instance.orden_asociada_id and instance.orden_asociada and instance.orden_asociada.cliente:
            c = instance.orden_asociada.cliente
            representation['cliente_nombre'] = c.nombre
            representation['cliente_documento'] = c.cedula
            representation['cliente_telefono1'] = c.telefono1
            representation['cliente_telefono2'] = c.telefono2
        else:
            representation['cliente_nombre'] = 'Cliente Nuevo'
            representation['cliente_documento'] = ''
            representation['cliente_telefono1'] = ''
            representation['cliente_telefono2'] = ''

        # inventario_items_detalle: solo usamos campos ya en el objeto prefetcheado.
        # Usamos el prefetch_cache si existe (puesto por el viewset), sin llamadas extra.
        items_data = []
        prefetched = getattr(instance, '_prefetched_objects_cache', {}).get('inventario_items', None)
        items_qs = prefetched if prefetched is not None else instance.inventario_items.select_related(
            'referencia', 'referencia__proveedor', 'categoria', 'subcategoria'
        ).all()
        for item in items_qs:
            ref = item.referencia
            items_data.append({
                'id_referencia': item.id_referencia,
                'producto_nombre': ref.nombre if ref else '',
                'variacion': item.variacion or '',
                'observacion': item.observacion or '',
                'categoria_nombre': item.categoria.nombre if item.categoria else '',
                'subcategoria_nombre': item.subcategoria.nombre if item.subcategoria else '',
                'proveedor_nombre': (ref.proveedor.nombre_empresa if ref and ref.proveedor else ''),
                'imagen': item.imagen,
                'grupo_id': item.grupo.id if item.grupo else None,
                'grupo_nombre': item.grupo.nombre if item.grupo else '',
                'grupo_observacion': item.grupo.observacion if item.grupo else '',
            })
        representation['inventario_items_detalle'] = items_data
        return representation
