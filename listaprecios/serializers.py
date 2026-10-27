from decimal import Decimal
from django.db import models, transaction

from rest_framework import serializers

from ordenes.serializers import SinMargenSinPermisoMixin
from ordenes.models import Referencia
from suministros.models import Categoria, Subcategoria
from .models import (
    CategoriaLista, GrupoTela, Multiplicador,
    LineaProducto, VarianteProducto, CargoVariante, PrecioVariante, EspecialLinea,
    Cotizacion, LineaCotizacion, EspecialCatalogo,
)
from .especiales import validar_configuracion, configuracion_base, configuracion_cargo
from .services import calcular_precio, costo_lista, precios_por_variante, opcionales_de_variante, multiplicador_efectivo, obtener_multiplicador_general, resumen_componentes, componentes_de, completar_grupos_material
from .referencias import categoria_variante, clasificacion, crear_configuracion, datos_referencia, subcategoria_pedida
from .disposicion import disposicion, mapa_disposiciones, variantes_visibles, retirada


def mapa_presentacion(contexto):
    if 'disposiciones' not in contexto:
        contexto['disposiciones'] = mapa_disposiciones()
    return contexto['disposiciones']


class DisposicionSubcategoriasSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    orden = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    retiradas = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)

    def validate(self, attrs):
        if 'orden' not in attrs and 'retiradas' not in attrs:
            raise serializers.ValidationError('Indica el orden o las subcategorías que se retiran.')
        return attrs


class RenombrarSubcategoriaSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=100, trim_whitespace=True, allow_blank=False)


class IdentidadLineaMixin:
    def to_representation(self, obj):
        data = super().to_representation(obj)
        data['es_decorativo'] = obj.es_decorativo or obj.slug == 'decorativos'
        if obj.referencia_id:
            data.update(datos_referencia(obj.referencia))
            config = disposicion(obj.referencia.nombre, mapa_presentacion(self.context))
            data['disposicion'] = config
            if 'variantes' in data:
                posiciones = {pk: i for i, pk in enumerate(config['orden'])}
                data['variantes'] = sorted((v for v in data['variantes'] if v['subcategoria'] not in config['retiradas']),
                                          key=lambda v: (posiciones.get(v['subcategoria'], len(posiciones)), v['orden'], v['id']))
        return data


class ClasificacionVarianteMixin:
    def to_representation(self, obj):
        data = super().to_representation(obj)
        categoria = categoria_variante(obj)
        data.update(nombre=obj.nombre_catalogo, categoria=categoria.pk if categoria else None, categoria_nombre=categoria.nombre if categoria else 'Sin clasificar',
                    subcategoria=obj.subcategoria_id, referencia=obj.linea.referencia_id)
        return data


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


def porcentaje_valido(valor, campo, minimo=Decimal('-100')):
    if valor is None or not minimo < valor <= 1000 or valor != valor.quantize(Decimal('0.01')):
        raise serializers.ValidationError({campo: f'Indica un porcentaje entre {minimo} y 1000, con máximo 2 decimales.'})
    return valor


def materiales_nuevos(antes, datos):
    """Materiales que pasan de vacío a configurado: 'tela' (metraje) y 'cuero' (decimetraje)."""
    return [material for material, campo in (('tela', 'metraje_tela'), ('cuero', 'decimetraje_cuero'))
            if datos.get(campo) and not (antes and getattr(antes, campo))]


class CargoVarianteSerializer(serializers.ModelSerializer):
    def validate_cantidad_maxima(self, valor):
        if valor is not None and not 1 <= valor <= 99:
            raise serializers.ValidationError('Indica de 1 a 99 unidades, o déjalo vacío.')
        return valor

    def _validar_valor_y_material(self, attrs, tipo):
        """(2026-10-27) Un cargo normal vale pesos enteros o un % del costo base y puede llevar
        tela/cuero; los cargos especiales (transporte, cojines, diferencias) solo pesos."""
        actual = self.instance
        modo = attrs.get('modo_valor', actual.modo_valor if actual else CargoVariante.MODO_PESOS)
        if tipo:
            if modo != CargoVariante.MODO_PESOS or attrs.get('metraje_tela') or attrs.get('decimetraje_cuero'):
                raise serializers.ValidationError({'modo_valor': 'Este tipo de cargo solo admite un valor en pesos, sin tela ni cuero.'})
        for campo in ('metraje_tela', 'decimetraje_cuero'):
            if campo in attrs:
                consumo = attrs[campo]
                if consumo is not None and not 0 <= consumo < 1000:
                    raise serializers.ValidationError({campo: 'Indica un consumo entre 0 y 999,99.'})
                attrs[campo] = consumo or None
        if actual and 'modo_valor' in attrs and modo != actual.modo_valor and 'valor' not in attrs:
            attrs['valor'] = Decimal(0)  # al cambiar de pesos a % (o al revés) el valor anterior no sirve
        if 'valor' not in attrs or attrs['valor'] is None:
            return
        if modo == CargoVariante.MODO_PORCENTAJE:
            variante = attrs.get('variante', actual.variante if actual else None)
            if variante is not None and variante.componentes.exists():
                raise serializers.ValidationError({'modo_valor': 'Una agrupación no tiene costo base propio: usa un cargo en pesos.'})
            porcentaje_valido(attrs['valor'], 'valor')
        else:
            try:
                pesos_enteros(attrs['valor'], permite_negativo=True)
            except serializers.ValidationError as e:
                raise serializers.ValidationError({'valor': e.detail})

    def validate(self, attrs):
        from .decorativos import DESCRIPCION
        tipo = attrs.get('tipo', self.instance.tipo if self.instance else '')
        self._validar_valor_y_material(attrs, tipo)
        if tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE:
            raise serializers.ValidationError('Este cargo se administra desde las opciones especiales de la colección.')
        if self.instance is not None:
            # «Cojines incluidos» se edita como cualquier cargo (nombre, valor y estado); su tipo no cambia.
            if 'tipo' in attrs and attrs['tipo'] != self.instance.tipo:
                raise serializers.ValidationError({'tipo': 'El tipo de un cargo no cambia.'})
            if 'descripcion' in attrs and not (attrs['descripcion'] or '').strip():
                raise serializers.ValidationError({'descripcion': 'Escribe el nombre del cargo.'})
        elif tipo == CargoVariante.TIPO_TRANSPORTE:
            if attrs['variante'].cargos.filter(tipo=CargoVariante.TIPO_TRANSPORTE).exists():
                raise serializers.ValidationError('Este producto ya tiene su transporte.')
            # Botón «Transporte»: llega solo con el tipo; costo de un envío $120.000, obligatorio.
            attrs.setdefault('descripcion', 'Transporte')
            if attrs.get('valor') is None:
                attrs['valor'] = Decimal(120000)
        elif tipo == CargoVariante.TIPO_DECORATIVOS:
            from .decorativos import valor_sugerido
            variante = attrs['variante']
            if variante.cargos.filter(tipo=CargoVariante.TIPO_DECORATIVOS).exists():
                raise serializers.ValidationError('Este producto ya incluye cojines.')
            # 2026-10-19: tiene valor (el costo de los 2 decorativos que cubre, igual para todos
            # los productos) y estado como los demás cargos; por defecto es obligatorio.
            attrs.setdefault('descripcion', DESCRIPCION)
            if attrs.get('valor') is None:
                attrs['valor'] = valor_sugerido()
        else:
            faltan = {c: 'Este campo es requerido.' for c in ('descripcion', 'valor') if attrs.get(c) is None}
            if faltan:
                raise serializers.ValidationError(faltan)
        # Las unidades por transporte solo aplican a un transporte (vacío = todas las de la línea).
        if tipo != CargoVariante.TIPO_TRANSPORTE:
            attrs.pop('unidades_por_transporte', None)
        elif attrs.get('unidades_por_transporte') is not None and not 1 <= attrs['unidades_por_transporte'] <= 999:
            raise serializers.ValidationError({'unidades_por_transporte': 'Indica de 1 a 999 unidades por transporte, o déjalo vacío.'})
        # Solo un opcional puede venir seleccionado de entrada; un obligatorio ya está en el precio.
        if not attrs.get('opcional', self.instance.opcional if self.instance else False):
            attrs['preseleccionado'] = False
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Un cargo nuevo queda al final de los del producto.
        ultimo = CargoVariante.objects.filter(variante=validated_data['variante']).aggregate(m=models.Max('orden'))['m']
        validated_data['orden'] = 0 if ultimo is None else ultimo + 1
        cargo = super().create(validated_data)
        completar_grupos_material(cargo.variante, materiales_nuevos(None, validated_data))
        return cargo

    @transaction.atomic
    def update(self, instance, validated_data):
        nuevos = materiales_nuevos(instance, validated_data)
        cargo = super().update(instance, validated_data)
        completar_grupos_material(cargo.variante, nuevos)
        return cargo

    class Meta:
        model = CargoVariante
        fields = ['id', 'variante', 'descripcion', 'valor', 'opcional', 'preseleccionado', 'especial', 'tipo', 'unidades_por_transporte', 'orden',
                  'modo_valor', 'metraje_tela', 'decimetraje_cuero', 'en_agrupacion', 'cantidad_maxima']
        read_only_fields = ['especial', 'orden']
        # El cargo «Cojines incluidos» puede llegar solo con el tipo: el servidor pone nombre y valor.
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
    nombre = serializers.CharField(max_length=150, required=False)
    categoria = serializers.PrimaryKeyRelatedField(queryset=CategoriaLista.objects.all(), required=False)
    subcategoria = serializers.PrimaryKeyRelatedField(queryset=Subcategoria.objects.all(), required=False)
    componentes = serializers.JSONField()

    def get_fields(self):
        campos = super().get_fields()
        if self.context.get('linea') and self.context['linea'].referencia_id:
            campos['categoria'] = serializers.PrimaryKeyRelatedField(queryset=Categoria.objects.all(), required=False, allow_null=True)
        return campos

    def validate(self, attrs):
        linea = self.context.get('linea')
        if linea and linea.referencia_id:
            sub = attrs.get('subcategoria')
            if sub:
                # Compatibilidad con conjuntos configurados antes de permitir un nombre nuevo.
                attrs['categoria'] = clasificacion(linea, attrs.get('categoria'), sub)
                attrs['nombre'] = sub.nombre
            elif not attrs.get('nombre') or not attrs.get('categoria'):
                raise serializers.ValidationError('Indica el nombre de la nueva subcategoría y su categoría.')
            elif len(attrs['nombre']) > 100:
                raise serializers.ValidationError({'nombre': 'Usa un nombre de hasta 100 caracteres.'})
        elif not attrs.get('nombre') or not attrs.get('categoria'):
            raise serializers.ValidationError('Indica el nombre y la categoría del conjunto.')
        return attrs


class VarianteProductoSerializer(ClasificacionVarianteMixin, serializers.ModelSerializer):
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
            'costo_base', 'costo_confirmado', 'publicado', 'costo_total_producto', 'metraje_tela', 'decimetraje_cuero', 'descuento_maximo', 'notas', 'cargos', 'precios',
            'multiplicador', 'multiplicador_nombre', 'multiplicador_efectivo', 'componentes', 'precios_venta', 'subcategoria',
            'variacion_cuero_tipo', 'variacion_cuero_valor',
        ]
        read_only_fields = ['costo_confirmado']
        validators = []  # La pertenencia/unicidad se valida bajo bloqueo al crear.

    def get_fields(self):
        campos = super().get_fields()
        linea = self.instance.linea if isinstance(self.instance, VarianteProducto) else None
        if linea is None and getattr(self, 'initial_data', {}).get('linea'):
            try:
                linea = LineaProducto.objects.filter(pk=self.initial_data['linea']).first()
            except (ValueError, TypeError):
                pass  # El campo relacional devuelve su error de validación habitual.
        if linea and linea.referencia_id:
            campos['categoria'] = serializers.PrimaryKeyRelatedField(source='categoria_referencia', queryset=Categoria.objects.all(), required=False, allow_null=True)
            campos['nombre'].required = False
        return campos

    def _validar_variacion_cuero(self, attrs):
        """Variación en cuero (2026-10-27): pesos enteros (puede bajar) o un % del costo base + cuero."""
        if 'variacion_cuero_tipo' not in attrs and 'variacion_cuero_valor' not in attrs:
            return
        actual = self.instance
        tipo = attrs.get('variacion_cuero_tipo', actual.variacion_cuero_tipo if actual else '')
        if actual and 'variacion_cuero_tipo' in attrs and tipo != actual.variacion_cuero_tipo and 'variacion_cuero_valor' not in attrs:
            attrs['variacion_cuero_valor'] = None  # cambiar de $ a % (o al revés) pide el valor de nuevo
        valor = attrs.get('variacion_cuero_valor', actual.variacion_cuero_valor if actual else None)
        if not tipo:
            attrs['variacion_cuero_valor'] = None
        elif actual is not None and actual.componentes.exists():
            raise serializers.ValidationError({'variacion_cuero_tipo': 'En una agrupación la variación en cuero la pone cada pieza.'})
        elif valor is None:
            return  # el tipo se elige primero; sin valor no cambia el precio
        elif tipo == VarianteProducto.VARIACION_PORCENTAJE:
            porcentaje_valido(valor, 'variacion_cuero_valor')
        else:
            try:
                pesos_enteros(valor, permite_negativo=True)
            except serializers.ValidationError as e:
                raise serializers.ValidationError({'variacion_cuero_valor': e.detail})

    def validate(self, attrs):
        self._validar_variacion_cuero(attrs)
        linea = attrs.get('linea', self.instance.linea if self.instance else None)
        if self.instance and linea.pk != self.instance.linea_id:
            raise serializers.ValidationError({'linea': 'Un producto no cambia de referencia. Crea su configuración en la referencia correcta.'})
        if linea and linea.referencia_id:
            sub = attrs.get('subcategoria', self.instance.subcategoria if self.instance else None)
            if not sub:
                raise serializers.ValidationError({'subcategoria': 'Los productos son las subcategorías asignadas en Referencias.'})
            if self.instance and sub.pk != self.instance.subcategoria_id:
                raise serializers.ValidationError({'subcategoria': 'La ficha de costos pertenece a su subcategoría y no se reasigna.'})
            if 'nombre' in attrs and attrs['nombre'] != sub.nombre:
                raise serializers.ValidationError({'nombre': 'El nombre pertenece a la subcategoría del catálogo.'})
            if not self.instance and linea.variantes.filter(subcategoria=sub).exists():
                raise serializers.ValidationError({'subcategoria': 'Esta subcategoría ya tiene su ficha de costos.'})
            categoria = attrs.get('categoria_referencia', self.instance.categoria_referencia if self.instance and 'subcategoria' not in attrs else None)
            if 'categoria' not in self.initial_data:
                categoria = None
            attrs['categoria_referencia'] = clasificacion(linea, categoria, sub)
            attrs['nombre'] = sub.nombre
            if 'costo_base' in attrs:
                attrs['costo_confirmado'] = True
        if attrs.get('publicado'):
            confirmado = attrs.get('costo_confirmado', self.instance.costo_confirmado if self.instance else False)
            if not linea.referencia_id or not self.instance:
                raise serializers.ValidationError({'publicado': 'Configura primero la subcategoría de Referencias.'})
            if retirada(self.instance):
                raise serializers.ValidationError({'publicado': 'Recupera esta subcategoría de la lista antes de publicarla.'})
            if not confirmado:
                raise serializers.ValidationError({'publicado': 'Guarda el costo de esta subcategoría antes de publicarla. Confirma también los costos de $0.'})
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        # Mismo bloqueo que sincronización y agrupaciones; vuelve a comprobar el costo actual.
        LineaProducto.objects.select_for_update().get(pk=instance.linea_id)
        self.instance = VarianteProducto.objects.select_for_update().select_related('linea__referencia', 'subcategoria').get(pk=instance.pk)
        self.validate(validated_data)
        nuevos = materiales_nuevos(self.instance, validated_data)
        variante = super().update(self.instance, validated_data)
        completar_grupos_material(variante, nuevos)
        return variante

    @transaction.atomic
    def create(self, validated_data):
        linea = validated_data['linea']
        LineaProducto.objects.select_for_update().get(pk=linea.pk)
        if linea.referencia_id and linea.variantes.filter(subcategoria=validated_data['subcategoria']).exists():
            raise serializers.ValidationError({'subcategoria': 'Esta subcategoría ya tiene su ficha de costos.'})
        return super().create(validated_data)

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
        return [{'id': c.id, 'variante': c.variante_id, 'variante_nombre': c.variante.nombre_catalogo, 'cantidad': c.cantidad,
                 'proveedor': c.variante.linea.referencia.proveedor_id if c.variante.linea.referencia_id else None,
                 'proveedor_nombre': c.variante.linea.referencia.proveedor.nombre_empresa if c.variante.linea.referencia_id else '',
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


class VarianteResumenSerializer(ClasificacionVarianteMixin, serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    # Un conjunto no tiene proveedor: la vista unificada lo muestra sin selector de proveedor.
    es_conjunto = serializers.SerializerMethodField()

    class Meta:
        model = VarianteProducto
        fields = ['id', 'nombre', 'orden', 'categoria', 'categoria_nombre', 'costo_confirmado', 'publicado', 'es_conjunto']

    def get_es_conjunto(self, obj):
        return bool(obj.componentes.all())


class LineaProductoResumenSerializer(IdentidadLineaMixin, serializers.ModelSerializer):
    """Cabeceras de administración: los cálculos se solicitan al abrir la colección."""
    variantes = VarianteResumenSerializer(many=True, read_only=True)
    resumen = serializers.SerializerMethodField()

    class Meta:
        model = LineaProducto
        fields = ['id', 'nombre', 'slug', 'notas', 'fotos', 'activo', 'orden', 'variantes', 'resumen', 'referencia']

    def get_resumen(self, obj):
        return True


class ReferenciaPrecioSerializer(serializers.ModelSerializer):
    linea = serializers.SerializerMethodField()

    class Meta:
        model = Referencia
        fields = ['id', 'linea']

    def to_representation(self, obj):
        return {**super().to_representation(obj), **datos_referencia(obj), 'disposicion': disposicion(obj.nombre, mapa_presentacion(self.context))}

    def get_linea(self, obj):
        linea = getattr(obj, 'lista_precios', None)
        return LineaProductoResumenSerializer(linea, context=self.context).data if linea else None


class LineaProductoSerializer(IdentidadLineaMixin, serializers.ModelSerializer):
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
            'variantes', 'especiales', 'created_at', 'updated_at', 'referencia', 'es_decorativo',
        ]
        # El formulario envía el nombre; la vista genera el slug al guardar.
        extra_kwargs = {'referencia': {'required': True, 'allow_null': False}}
        read_only_fields = ['created_at', 'updated_at', 'nombre', 'slug']

    def validate(self, attrs):
        ref = attrs.get('referencia', self.instance.referencia if self.instance else None)
        if self.instance and self.instance.referencia_id and ref.pk != self.instance.referencia_id:
            raise serializers.ValidationError({'referencia': 'La referencia de una lista de precios no se cambia.'})
        if ref and 'nombre' in self.initial_data and self.initial_data['nombre'] != ref.nombre:
            raise serializers.ValidationError({'nombre': 'El nombre pertenece a Referencias; aquí solo se configuran precios.'})
        if attrs.get('activo') and (not ref or not self.instance or not self.instance.variantes.exists()):
            raise serializers.ValidationError({'activo': 'Agrega y revisa al menos un producto antes de publicar los precios.'})
        if attrs.get('activo') and ref:
            productos = list(self.instance.variantes.all())
            if {v.subcategoria_id for v in productos} != set(ref.subcategorias.values_list('pk', flat=True)):
                raise serializers.ValidationError({'activo': 'Actualiza las subcategorías antes de publicar.'})
            visibles = variantes_visibles(self.instance, mapa_presentacion(self.context))
            if not visibles:
                raise serializers.ValidationError({'activo': 'No hay subcategorías visibles para publicar.'})
            if any(not v.costo_confirmado for v in visibles):
                raise serializers.ValidationError({'activo': 'Confirma el costo de todas las subcategorías antes de publicar.'})
        return attrs

    def create(self, validated_data):
        validated_data.setdefault('activo', False)
        sub = subcategoria_pedida(getattr(self, 'initial_data', {}).get('subcategoria'))
        return crear_configuracion(validated_data.pop('referencia'), subcategoria=sub, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        # Comparte bloqueo con la incorporación de subcategorías y los conjuntos.
        actual = LineaProducto.objects.select_for_update().get(pk=instance.pk)
        self.instance = actual
        self.validate(validated_data)
        resultado = super().update(actual, validated_data)
        # Compatibilidad con la publicación anterior de una colección completa.
        if 'activo' in validated_data:
            ids = [v.pk for v in variantes_visibles(actual, mapa_presentacion(self.context))]
            actual.variantes.filter(pk__in=ids).update(publicado=validated_data['activo'])
        return resultado

    def get_especiales(self, obj):
        return EspecialLineaSerializer(obj.especiales.all(), many=True, context=self.context).data


# ------------------------------------------------------------------
# Serializers de catálogo (vendedor) — nunca incluyen costo_base, metraje_tela
# ni cargos crudos, solo precios de venta ya calculados.
# ------------------------------------------------------------------

class VarianteCatalogoSerializer(ClasificacionVarianteMixin, serializers.ModelSerializer):
    precios = serializers.SerializerMethodField()
    opcionales = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    componentes = serializers.SerializerMethodField()
    proveedores = serializers.SerializerMethodField()

    class Meta:
        model = VarianteProducto
        fields = ['id', 'categoria', 'categoria_nombre', 'nombre', 'orden', 'notas', 'precios', 'opcionales', 'componentes', 'proveedores', 'decorativos_incluidos', 'transporte', 'incluidos']

    decorativos_incluidos = serializers.SerializerMethodField()
    transporte = serializers.SerializerMethodField()
    incluidos = serializers.SerializerMethodField()

    def get_incluidos(self, obj):
        """Cargos obligatorios (ya van en el precio): la consulta los muestra seleccionados y fijos,
        solo con su nombre. «Cojines incluidos» tiene su propio aviso. Un conjunto suma los de sus piezas."""
        propios = [c for c in obj.cargos.all() if not c.opcional and c.tipo != CargoVariante.TIPO_DECORATIVOS]
        piezas = [c for comp in componentes_de(obj) for c in comp.variante.cargos.all() if not c.opcional and c.tipo != CargoVariante.TIPO_DECORATIVOS]
        nombres = []
        for c in propios + piezas:
            if c.descripcion not in nombres:
                nombres.append(c.descripcion)
        return nombres

    def get_transporte(self, obj):
        """Transporte por envío de un producto suelto: lo que suma por unidad y cuántas unidades
        lleva; la consulta lo usa para no cobrarlo de más (un conjunto ya trae uno solo)."""
        from .transportes import cargo_transporte, valor_venta
        cargo = None if componentes_de(obj) else cargo_transporte(obj)
        if cargo is None:
            return None
        return {'id': cargo.pk, 'valor': valor_venta(obj, [cargo.pk], general=self.context.get('multiplicador_general')),
                'cupo': cargo.unidades_por_transporte, 'opcional': cargo.opcional}

    def get_componentes(self, obj):
        """Si es un juego: «1 Mesa de 6 + 6 Silla de comedor» (vacío si no)."""
        return resumen_componentes(obj)

    def get_proveedores(self, obj):
        piezas = componentes_de(obj)
        referencias = [c.variante.linea.referencia for c in piezas] if piezas else [obj.linea.referencia]
        proveedores = {r.proveedor_id: {'id': r.proveedor_id, 'nombre': r.proveedor.nombre_empresa}
                       for r in referencias if r}
        return list(proveedores.values())

    def get_decorativos_incluidos(self, obj):
        """Decorativos sin cobro por unidad cuando «Cojines incluidos» es obligatorio; si es
        opcional viaja en `opcionales` (marcado `decorativos`) y cuenta solo si se elige."""
        from .decorativos import UNIDADES_POR_PRODUCTO, cargo_decorativos
        cargo = cargo_decorativos(obj)
        return UNIDADES_POR_PRODUCTO if cargo and not cargo.opcional else 0

    def get_precios(self, obj):
        filas = precios_por_variante(obj, grupos=self.context.get('grupos'), multiplicador_general=self.context.get('multiplicador_general'))
        if obj.linea.es_decorativo or self.context.get('linea_decorativos') == obj.linea_id:
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


class LineaCatalogoSerializer(IdentidadLineaMixin, serializers.ModelSerializer):
    variantes = VarianteCatalogoSerializer(many=True, read_only=True)
    desde = serializers.SerializerMethodField()

    class Meta:
        model = LineaProducto
        fields = ['id', 'nombre', 'slug', 'notas', 'fotos', 'orden', 'variantes', 'desde']

    def get_desde(self, obj):
        grupos = self.context.get('grupos')
        multiplicador_general = self.context.get('multiplicador_general')
        precios = []
        for variante in variantes_visibles(obj, mapa_presentacion(self.context)):
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
            'opcionales', 'notas', 'foto', 'incluido', 'transporte_compartido',
        ]
        read_only_fields = ['id', 'subtotal', 'margen', 'incluido', 'transporte_compartido']


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
