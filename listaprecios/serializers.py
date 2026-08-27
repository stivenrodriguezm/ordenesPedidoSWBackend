from rest_framework import serializers

from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante,
)
from .services import calcular_precio, precios_por_variante, opcionales_de_variante, multiplicador_efectivo


class GrupoTelaSerializer(serializers.ModelSerializer):
    unidad_medida = serializers.ReadOnlyField()

    class Meta:
        model = GrupoTela
        fields = ['id', 'nombre', 'tipo', 'precio_por_metro', 'orden', 'unidad_medida']


class MultiplicadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Multiplicador
        fields = ['id', 'nombre', 'valor', 'es_general', 'orden']


class CategoriaListaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoriaLista
        fields = ['id', 'nombre', 'slug', 'orden', 'activo']


class CategoriaListaPublicSerializer(serializers.ModelSerializer):
    """Vista sin campos de margen — para el catálogo de vendedor (filtros
    por categoría/tipo de producto), gated solo por VER_LISTA_PRECIOS."""
    class Meta:
        model = CategoriaLista
        fields = ['id', 'nombre', 'slug', 'orden']


class CargoVarianteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CargoVariante
        fields = ['id', 'variante', 'descripcion', 'valor', 'opcional']


class PrecioVarianteSerializer(serializers.ModelSerializer):
    grupo_nombre = serializers.CharField(source='grupo.nombre', read_only=True)
    precio_calculado = serializers.SerializerMethodField()

    class Meta:
        model = PrecioVariante
        fields = ['id', 'variante', 'grupo', 'grupo_nombre', 'precio_manual', 'precio_calculado']

    def get_precio_calculado(self, obj):
        return calcular_precio(obj.variante, obj.grupo, multiplicador_general=self.context.get('multiplicador_general'))


class VarianteProductoSerializer(serializers.ModelSerializer):
    """Vista de administración — incluye costo_base/metraje_tela, gated por
    VER_COSTOS_LISTA_PRECIOS en la vista."""
    cargos = CargoVarianteSerializer(many=True, read_only=True)
    precios = PrecioVarianteSerializer(many=True, read_only=True)
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    multiplicador_nombre = serializers.SerializerMethodField()
    multiplicador_efectivo = serializers.SerializerMethodField()

    class Meta:
        model = VarianteProducto
        fields = [
            'id', 'linea', 'categoria', 'categoria_nombre', 'nombre', 'orden',
            'costo_base', 'metraje_tela', 'notas', 'cargos', 'precios',
            'multiplicador', 'multiplicador_nombre', 'multiplicador_efectivo',
        ]

    def get_multiplicador_nombre(self, obj):
        if obj.multiplicador_id:
            return obj.multiplicador.nombre
        general = self.context.get('multiplicador_general_obj')
        return f"{general.nombre} (general)" if general else "General"

    def get_multiplicador_efectivo(self, obj):
        return multiplicador_efectivo(obj, multiplicador_general=self.context.get('multiplicador_general'))


class LineaProductoSerializer(serializers.ModelSerializer):
    """Vista de administración — incluye variantes anidadas (con costos y su
    propia categoría/tipo de producto cada una). La edición de
    variantes/cargos/precios se hace vía sus propios endpoints
    (VarianteProductoViewSet, etc.), igual que CostoAdicionalInventario
    respecto a Inventario."""
    variantes = VarianteProductoSerializer(many=True, read_only=True)

    class Meta:
        model = LineaProducto
        fields = [
            'id', 'nombre', 'slug', 'notas', 'fotos', 'activo', 'orden',
            'variantes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


# ------------------------------------------------------------------
# Serializers de catálogo (vendedor) — nunca incluyen costo_base, metraje_tela
# ni cargos crudos, solo precios de venta ya calculados.
# ------------------------------------------------------------------

class VarianteCatalogoSerializer(serializers.ModelSerializer):
    precios = serializers.SerializerMethodField()
    opcionales = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)

    class Meta:
        model = VarianteProducto
        fields = ['id', 'categoria', 'categoria_nombre', 'nombre', 'orden', 'notas', 'precios', 'opcionales']

    def get_precios(self, obj):
        return precios_por_variante(obj, grupos=self.context.get('grupos'), multiplicador_general=self.context.get('multiplicador_general'))

    def get_opcionales(self, obj):
        return opcionales_de_variante(obj)


class LineaCatalogoSerializer(serializers.ModelSerializer):
    variantes = VarianteCatalogoSerializer(many=True, read_only=True)
    desde = serializers.SerializerMethodField()

    class Meta:
        model = LineaProducto
        fields = ['id', 'nombre', 'slug', 'notas', 'fotos', 'orden', 'variantes', 'desde']

    def get_desde(self, obj):
        grupos = self.context.get('grupos')
        multiplicador_general = self.context.get('multiplicador_general')
        precios = []
        for variante in obj.variantes.all():
            for fila in precios_por_variante(variante, grupos=grupos, multiplicador_general=multiplicador_general):
                if fila['precio'] is not None:
                    precios.append(fila['precio'])
        return min(precios) if precios else None
