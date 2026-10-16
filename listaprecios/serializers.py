from decimal import Decimal

from rest_framework import serializers

from ordenes.serializers import SinMargenSinPermisoMixin
from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante, EspecialLinea,
    Cotizacion, LineaCotizacion, EspecialCatalogo,
)
from .especiales import validar_configuracion, configuracion_base, configuracion_cargo
from .services import calcular_precio, costo_lista, precios_por_variante, opcionales_de_variante, multiplicador_efectivo, obtener_multiplicador_general, resumen_componentes


def pesos_enteros(valor, permite_negativo=False):
    if valor is not None and (valor != valor.to_integral_value() or (not permite_negativo and valor < 0)):
        raise serializers.ValidationError('Indica un importe en pesos enteros, sin centavos.' if permite_negativo else 'Indica un importe en pesos enteros, mayor o igual a cero.')
    return valor


class GrupoTelaSerializer(serializers.ModelSerializer):
    unidad_medida = serializers.ReadOnlyField()

    def validate_precio_por_metro(self, valor):
        return pesos_enteros(valor)

    class Meta:
        model = GrupoTela
        fields = ['id', 'nombre', 'tipo', 'precio_por_metro', 'orden', 'unidad_medida']


class MultiplicadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Multiplicador
        fields = ['id', 'nombre', 'valor', 'es_general', 'orden']

    def validate_valor(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('El multiplicador debe ser mayor a cero.')
        return value

    def validate_es_general(self, value):
        # El general solo se reemplaza marcando otro (transición atómica en
        # establecer_multiplicador_general); nunca puede quedar el catálogo sin uno.
        if self.instance is not None and self.instance.es_general and value is False:
            raise serializers.ValidationError('Para cambiar el multiplicador general, marca otro como general.')
        return value


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
    def validate_valor(self, valor):
        return pesos_enteros(valor, permite_negativo=True)

    def validate(self, attrs):
        from .decorativos import DESCRIPCION
        tipo = attrs.get('tipo', self.instance.tipo if self.instance else '')
        if tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE:
            raise serializers.ValidationError('Este cargo se administra desde las opciones especiales de la colección.')
        if self.instance is not None:
            if self.instance.tipo == CargoVariante.TIPO_DECORATIVOS:
                raise serializers.ValidationError('«Cojines incluidos» no se modifica: quítalo y agrégalo de nuevo si hace falta.')
            if attrs.get('tipo', '') != self.instance.tipo:
                raise serializers.ValidationError({'tipo': 'El tipo de un cargo no cambia.'})
        elif tipo == CargoVariante.TIPO_DECORATIVOS:
            variante = attrs['variante']
            if variante.cargos.filter(tipo=CargoVariante.TIPO_DECORATIVOS).exists():
                raise serializers.ValidationError('Este producto ya incluye cojines.')
            # Fijo, sin valor y no opcional: lo que viaja con el producto es el derecho a 2 decorativos.
            attrs.update(descripcion=DESCRIPCION, valor=Decimal(0), opcional=False)
        else:
            faltan = {c: 'Este campo es requerido.' for c in ('descripcion', 'valor') if attrs.get(c) is None}
            if faltan:
                raise serializers.ValidationError(faltan)
        # Solo un opcional puede venir seleccionado de entrada; un obligatorio ya está en el precio.
        if not attrs.get('opcional', self.instance.opcional if self.instance else False):
            attrs['preseleccionado'] = False
        return attrs

    class Meta:
        model = CargoVariante
        fields = ['id', 'variante', 'descripcion', 'valor', 'opcional', 'preseleccionado', 'especial', 'tipo']
        read_only_fields = ['especial']
        # El cargo «Cojines incluidos» llega solo con el tipo: descripción y valor los pone el servidor.
        extra_kwargs = {'descripcion': {'required': False}, 'valor': {'required': False}}


class PrecioVarianteSerializer(serializers.ModelSerializer):
    grupo_nombre = serializers.CharField(source='grupo.nombre', read_only=True)
    precio_calculado = serializers.SerializerMethodField()

    def validate_precio_manual(self, valor):
        return pesos_enteros(valor)

    class Meta:
        model = PrecioVariante
        fields = ['id', 'variante', 'grupo', 'grupo_nombre', 'precio_manual', 'precio_calculado']

    def get_precio_calculado(self, obj):
        return calcular_precio(obj.variante, obj.grupo, multiplicador_general=self.context.get('multiplicador_general'))


class OrdenVariantesSerializer(serializers.Serializer):
    variantes = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)
    orden_anterior = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)


class AgrupacionNuevaSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=150)
    categoria = serializers.PrimaryKeyRelatedField(queryset=CategoriaLista.objects.all())
    componentes = serializers.JSONField()


class VarianteProductoSerializer(serializers.ModelSerializer):
    """Vista de administración — incluye costo_base/metraje_tela, gated por
    VER_COSTOS_LISTA_PRECIOS en la vista."""
    cargos = CargoVarianteSerializer(many=True, read_only=True)
    precios = PrecioVarianteSerializer(many=True, read_only=True)
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    multiplicador_nombre = serializers.SerializerMethodField()
    multiplicador_efectivo = serializers.SerializerMethodField()
    componentes = serializers.SerializerMethodField()
    precios_venta = serializers.SerializerMethodField()
    costo_total_producto = serializers.SerializerMethodField()

    class Meta:
        model = VarianteProducto
        fields = [
            'id', 'linea', 'categoria', 'categoria_nombre', 'nombre', 'orden',
            'costo_base', 'costo_total_producto', 'metraje_tela', 'decimetraje_cuero', 'descuento_maximo', 'notas', 'cargos', 'precios',
            'multiplicador', 'multiplicador_nombre', 'multiplicador_efectivo', 'componentes', 'precios_venta',
        ]

    def validate_costo_base(self, valor):
        return pesos_enteros(valor)

    def validate_descuento_maximo(self, valor):
        if valor is not None and not 0 <= valor <= 100:
            raise serializers.ValidationError('El tope debe estar entre 0 y 100 %.')
        return valor

    def validate_metraje_tela(self, valor):
        if valor is not None and valor <= 0:
            raise serializers.ValidationError('Indica un consumo de tela mayor a cero o desactiva esta opción.')
        return valor

    def validate_decimetraje_cuero(self, valor):
        if valor is not None and valor <= 0:
            raise serializers.ValidationError('Indica un decimetraje mayor a cero o desactiva esta opción.')
        return valor

    def get_componentes(self, obj):
        return [{'id': c.id, 'variante': c.variante_id, 'variante_nombre': c.variante.nombre, 'cantidad': c.cantidad,
                 'costo_unitario': str(c.costo_unitario) if c.costo_unitario is not None else None,
                 'multiplicador': str(c.multiplicador) if c.multiplicador is not None else None, 'adicionales': c.adicionales}
                for c in obj.componentes.all()]

    def get_costo_total_producto(self, obj):
        return str(costo_lista(obj, sin_material=True))

    def get_precios_venta(self, obj):
        return precios_por_variante(obj, grupos=self.context.get('grupos'), multiplicador_general=self.context.get('multiplicador_general'))

    def get_multiplicador_nombre(self, obj):
        if obj.multiplicador_id:
            return obj.multiplicador.nombre
        general = self.context.get('multiplicador_general_obj')
        return f"{general.nombre} (general)" if general else "General"

    def get_multiplicador_efectivo(self, obj):
        return multiplicador_efectivo(obj, multiplicador_general=self.context.get('multiplicador_general'))


class EspecialLineaSerializer(serializers.ModelSerializer):
    """`valor` conserva el contrato histórico de costos; `diferencia_precio` son pesos finales."""
    aplicaciones = serializers.SerializerMethodField()
    configuracion = serializers.JSONField(required=False)
    configuracion_efectiva = serializers.SerializerMethodField()
    formato_anterior = serializers.SerializerMethodField()

    def validate_configuracion(self, valor):
        return validar_configuracion(valor)

    def validate(self, attrs):
        if ("configuracion" in attrs or (self.instance and self.instance.configuracion)) and ("diferencia_precio" in attrs or "valor" in attrs):
            raise serializers.ValidationError("Envía la configuración de costo, sin mezclarla con el formato anterior.")
        return attrs

    def get_configuracion_efectiva(self, obj):
        return configuracion_base(obj, self.context.get("multiplicador_general"))

    def get_formato_anterior(self, obj):
        return not bool(obj.configuracion)

    diferencia_precio = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, write_only=True)

    def validate_diferencia_precio(self, valor):
        return pesos_enteros(valor, permite_negativo=True)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        cargos = list(obj.cargos.all())
        directo = bool(cargos) and all(c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO for c in cargos)
        general = self.context.get('multiplicador_general')
        diferencia = obj.valor if directo or obj.configuracion else obj.valor * (general if general is not None else obtener_multiplicador_general())
        data['diferencia_precio'] = None if obj.configuracion else format(diferencia.normalize(), 'f')
        return data

    def validate_valor(self, valor):
        return pesos_enteros(valor, permite_negativo=True)

    class Meta:
        model = EspecialLinea
        fields = ['id', 'linea', 'nombre', 'descripcion', 'valor', 'diferencia_precio', 'orden', 'aplicaciones', 'configuracion', 'configuracion_efectiva', 'formato_anterior']

    def get_aplicaciones(self, obj):
        return [{'variante': c.variante_id, 'valor': c.valor, 'cargo': c.id, 'configuracion': c.configuracion_especial,
                 'configuracion_efectiva': configuracion_cargo(c, self.context.get('multiplicador_general')),
                 'diferencia_precio': None if c.tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE else c.valor if c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO else c.valor * multiplicador_efectivo(c.variante, self.context.get('multiplicador_general'))}
                for c in obj.cargos.all()]

    def validate_nombre(self, value):
        if not value.strip():
            raise serializers.ValidationError('Ponle un nombre.')
        return value.strip()


class EspecialCatalogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EspecialCatalogo
        fields = ['id', 'nombre', 'configuracion', 'origen']


class VarianteResumenSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)

    class Meta:
        model = VarianteProducto
        fields = ['id', 'nombre', 'orden', 'categoria', 'categoria_nombre']


class LineaProductoResumenSerializer(serializers.ModelSerializer):
    """Cabeceras de administración: los cálculos se solicitan al abrir la colección."""
    variantes = VarianteResumenSerializer(many=True, read_only=True)
    resumen = serializers.SerializerMethodField()

    class Meta:
        model = LineaProducto
        fields = ['id', 'nombre', 'slug', 'notas', 'fotos', 'activo', 'orden', 'variantes', 'resumen']

    def get_resumen(self, obj):
        return True


class LineaProductoSerializer(serializers.ModelSerializer):
    """Vista de administración — incluye variantes anidadas (con costos y su
    propia categoría/tipo de producto cada una). La edición de
    variantes/cargos/precios se hace vía sus propios endpoints
    (VarianteProductoViewSet, etc.), igual que CostoAdicionalInventario
    respecto a Inventario."""
    variantes = VarianteProductoSerializer(many=True, read_only=True)
    especiales = serializers.SerializerMethodField()

    class Meta:
        model = LineaProducto
        fields = [
            'id', 'nombre', 'slug', 'notas', 'fotos', 'activo', 'orden',
            'variantes', 'especiales', 'created_at', 'updated_at',
        ]
        # El formulario envía el nombre; la vista genera el slug al guardar.
        extra_kwargs = {'slug': {'required': False, 'allow_blank': True}}
        read_only_fields = ['created_at', 'updated_at']

    def get_especiales(self, obj):
        return EspecialLineaSerializer(obj.especiales.all(), many=True, context=self.context).data


# ------------------------------------------------------------------
# Serializers de catálogo (vendedor) — nunca incluyen costo_base, metraje_tela
# ni cargos crudos, solo precios de venta ya calculados.
# ------------------------------------------------------------------

class VarianteCatalogoSerializer(serializers.ModelSerializer):
    precios = serializers.SerializerMethodField()
    opcionales = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    componentes = serializers.SerializerMethodField()

    class Meta:
        model = VarianteProducto
        fields = ['id', 'categoria', 'categoria_nombre', 'nombre', 'orden', 'notas', 'precios', 'opcionales', 'componentes', 'decorativos_incluidos']

    decorativos_incluidos = serializers.SerializerMethodField()

    def get_componentes(self, obj):
        """Si es un juego: «1 Mesa de 6 + 6 Silla de comedor» (vacío si no)."""
        return resumen_componentes(obj)

    def get_decorativos_incluidos(self, obj):
        """Decorativos sin cobro por unidad («Cojines incluidos»); 0 si no trae."""
        from .decorativos import UNIDADES_POR_PRODUCTO, da_decorativos
        return UNIDADES_POR_PRODUCTO if da_decorativos(obj) else 0

    def get_precios(self, obj):
        filas = precios_por_variante(obj, grupos=self.context.get('grupos'), multiplicador_general=self.context.get('multiplicador_general'))
        if self.context.get('linea_decorativos') == obj.linea_id:
            # Un decorativo informa cuánto cubre el cupo en cada grupo: completo en grupo 1 o 2;
            # de ahí en adelante, lo que valdría en grupo 2 (el resto se cobra).
            incluidos = self.context.get('grupos_incluidos') or []
            refs = [f['precio'] for f in filas if f['grupo'] in incluidos and f['precio'] is not None]
            for f in filas:
                if f['precio'] is not None:
                    f['tope_incluido'] = f['precio'] if f['grupo'] is None or f['grupo'] in incluidos else min(f['precio'], max(refs) if refs else 0)
        return filas

    def get_opcionales(self, obj):
        return opcionales_de_variante(obj, multiplicador_general=self.context.get('multiplicador_general'), grupos=self.context.get('grupos'))


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


# ------------------------------------------------------------------
# Serializers de Cotizaciones (P09-01 / F01)
# ------------------------------------------------------------------

class LineaCotizacionSerializer(SinMargenSinPermisoMixin, serializers.ModelSerializer):
    margen = serializers.SerializerMethodField(read_only=True)

    def get_margen(self, obj):
        if obj.costo_estimado is not None:
            return (obj.subtotal - (obj.costo_estimado * obj.cantidad)).quantize(Decimal('0.01'))
        return None

    class Meta:
        model = LineaCotizacion
        fields = [
            'id', 'variante', 'linea_nombre', 'variante_nombre', 'categoria_nombre',
            'grupo_tela', 'grupo_nombre', 'cantidad', 'precio_unitario', 'subtotal',
            'costo_estimado', 'margen',
            'opcionales', 'notas', 'foto', 'incluido',
        ]
        read_only_fields = ['id', 'subtotal', 'margen', 'incluido']


class CotizacionSerializer(SinMargenSinPermisoMixin, serializers.ModelSerializer):
    lineas = LineaCotizacionSerializer(many=True, required=False)
    asesor_username = serializers.CharField(source='asesor.username', read_only=True)
    cliente_nombre_completo = serializers.SerializerMethodField(read_only=True)
    margen_total = serializers.SerializerMethodField(read_only=True)

    def get_margen_total(self, obj):
        lineas = getattr(obj, '_prefetched_lineas', None)
        if lineas is None:
            lineas = list(obj.lineas.all())
        lineas_con_costo = [l for l in lineas if l.costo_estimado is not None]
        if not lineas_con_costo:
            return None
        costo_total = sum((l.costo_estimado * l.cantidad for l in lineas_con_costo), Decimal('0.00'))
        return (obj.total - costo_total).quantize(Decimal('0.01'))

    class Meta:
        model = Cotizacion
        fields = [
            'id', 'numero', 'cliente', 'cliente_nombre', 'cliente_nombre_completo',
            'cliente_documento', 'cliente_telefono', 'cliente_email',
            'asesor', 'asesor_nombre', 'asesor_username',
            'fecha_creacion', 'fecha_vencimiento', 'estado', 'version', 'version_calculo',
            'subtotal', 'descuento', 'descuento_porcentaje', 'total', 'margen_total',
            'notas', 'venta_asociada', 'fecha_conversion', 'lineas',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'numero', 'asesor', 'asesor_nombre', 'fecha_creacion',
            'version', 'subtotal', 'total', 'margen_total', 'venta_asociada', 'fecha_conversion',
            'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        validated_data.pop('lineas', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('lineas', None)
        return super().update(instance, validated_data)

    def get_cliente_nombre_completo(self, obj):
        if obj.cliente:
            return obj.cliente.nombre
        return obj.cliente_nombre or 'Sin cliente'
