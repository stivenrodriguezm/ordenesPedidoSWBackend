import random
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro, RemisionItemManual, RemisionEvento,
    RemisionInventarioTexto, GrupoInventario, GrupoInventarioComponente,
    Sede, Zona, HistorialTraslado, CostoAdicionalInventario,
    ItemInventarioTelaCuero
)
from ordenes.models import Venta, Referencia
from ordenes.permissions import check_feature_permission


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
        ]

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
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        productos_data = validated_data.pop('productos', [])
        factura = FacturaProveedor.objects.create(**validated_data)
        for prod_data in productos_data:
            _crear_item_inventario(prod_data, factura)
        return factura

    @transaction.atomic
    def update(self, instance, validated_data):
        productos_data = validated_data.pop('productos', None)

        # Actualizar campos de la factura
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Si se actualizó el id_manual, actualizarlo en los items de inventario vinculados
        if instance.id_manual is not None:
            instance.items_inventario.update(factura_manual=instance.id_manual or '')

        # Si se envían productos en el update: se reemplazan por completo los
        # ítems editables (borrar + recrear, igual que en create), en vez de
        # emparejar por índice. Los ítems que ya fueron entregados se
        # preservan siempre intactos — el formulario de edición los muestra en
        # modo solo-lectura y nunca los incluye en `productos_data`. Tener una
        # venta asociada NO basta para bloquear un ítem: puede pasar tiempo en
        # bodega antes de entregarse, y en ese lapso debe seguir siendo editable.
        if productos_data is not None:
            instance.items_inventario.exclude(disponibilidad='entregado').delete()
            for prod_data in productos_data:
                _crear_item_inventario(prod_data, instance)

        return instance


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
            'referencia', 'descripcion', 'cantidad', 'venta', 'detalle_pedido',
        ]
        extra_kwargs = {
            'categoria': {'required': False, 'allow_null': True},
            'subcategoria': {'required': False, 'allow_null': True},
            'referencia': {'required': False, 'allow_blank': True},
            'descripcion': {'required': False, 'allow_blank': True},
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
            'inventario_items', 'items_manuales', 'descripciones_inventario',
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

        if items:
            retenidos = items_retenidos_por_remision(i.pk for i in items)
            for item in items:
                if item.pk in retenidos:
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya está en la remisión #{retenidos[item.pk]}.'
                    })
                if item.disponibilidad in ('despachado', 'entregado'):
                    raise serializers.ValidationError({
                        'inventario_items': f'El producto {item.pk} ya fue {item.get_disponibilidad_display().lower()}.'
                    })
        if 'descripciones_inventario' in attrs:
            attrs['descripciones_inventario'] = self._limpiar_descripciones(
                attrs['descripciones_inventario'], {i.pk for i in items}
            )
        return attrs

    @staticmethod
    def _limpiar_descripciones(textos, ids_remision):
        """Solo textos no vacíos de productos que van en la remisión."""
        ajenos = [k for k in textos if k not in ids_remision]
        if ajenos:
            raise serializers.ValidationError({
                'descripciones_inventario': f'El producto {ajenos[0]} no está en la remisión.'
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
        if 'descripciones_inventario' in attrs:
            attrs['descripciones_inventario'] = self._limpiar_descripciones(
                attrs['descripciones_inventario'], set(inst.inventario_items.values_list('pk', flat=True))
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        inventario_items_data = validated_data.pop('inventario_items', [])
        ventas_data = validated_data.pop('ventas', [])
        manuales_data = validated_data.pop('items_manuales', [])
        textos = validated_data.pop('descripciones_inventario', {})
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            validated_data['creado_por'] = request.user

        remision = super().create(validated_data)
        if ventas_data:
            remision.ventas.set(ventas_data)
        if inventario_items_data:
            remision.inventario_items.set(inventario_items_data)
            # La disponibilidad ('por_despachar') la actualiza perform_create del viewset en bulk
        if manuales_data:
            RemisionItemManual.objects.bulk_create([
                RemisionItemManual(remision=remision, **{k: v for k, v in m.items() if k != 'id'})
                for m in manuales_data
            ])
        if textos:
            self._guardar_descripciones(remision, textos)
        return remision

    @transaction.atomic
    def update(self, instance, validated_data):
        # Las ventas y los productos de inventario se fijan al crear (mueven la
        # disponibilidad del inventario). Los productos escritos o de pedido sí se editan.
        validated_data.pop('inventario_items', None)
        validated_data.pop('ventas', None)
        manuales = validated_data.pop('items_manuales', None)
        textos = validated_data.pop('descripciones_inventario', None)
        instance = super().update(instance, validated_data)
        if manuales is not None:
            self._sincronizar_manuales(instance, manuales)
        if textos is not None:
            self._guardar_descripciones(instance, textos)
        return instance

    @staticmethod
    def _guardar_descripciones(remision, textos):
        """Deja exactamente estos textos; los productos sin texto vuelven al del inventario."""
        RemisionInventarioTexto.objects.filter(remision=remision).delete()
        RemisionInventarioTexto.objects.bulk_create([
            RemisionInventarioTexto(remision=remision, inventario_id=pk, descripcion=texto)
            for pk, texto in textos.items()
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
        textos = {t.inventario_id: t.descripcion for t in instance.textos_inventario.all()}
        for item in items_qs:
            ref = item.referencia
            items_data.append({
                'id_referencia': item.id_referencia,
                'producto_nombre': ref.nombre if ref else '',
                'variacion': item.variacion or '',
                'observacion': item.observacion or '',
                'descripcion_remision': textos.get(item.id_referencia, ''),
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

        request = self.context.get('request')
        if request is not None and getattr(request.user, 'role', None) != 'transportador' \
                and not tiene_permiso(request, 'VER_COSTO_ENTREGA_REMISION'):
            representation.pop('costo_entrega', None)
        return representation
