"""Identidad y clasificación del catálogo: siempre las Referencias existentes."""
from django.db import IntegrityError, transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from rest_framework.exceptions import ValidationError

from ordenes.models import Referencia
from .models import LineaProducto, VarianteProducto


def productos_actuales(queryset=None):
    """Una opción comercial es la ficha de una subcategoría asignada a su Referencia.

    Los productos anteriores siguen existiendo para documentos históricos, pero no
    entran en los selectores de nuevas consultas/ventas, incluso después de restaurar SQL.
    """
    queryset = queryset if queryset is not None else VarianteProducto.objects.all()
    return queryset.filter(linea__referencia__isnull=False, subcategoria__isnull=False,
                           linea__referencia__subcategorias=F('subcategoria_id')).distinct()


def productos_publicados(queryset=None):
    """Estado individual en el catálogo unificado; compatibilidad de cálculos históricos."""
    queryset = queryset if queryset is not None else VarianteProducto.objects.all()
    return queryset.filter(Q(linea__referencia__isnull=False, publicado=True) |
                           Q(linea__referencia__isnull=True, linea__activo=True))


def ordenar_productos_actuales(queryset):
    from .disposicion import clave_referencia, mapa_disposiciones
    configuraciones = {clave: d for clave, d in mapa_disposiciones().items() if d['orden']}
    referencias = {}
    if configuraciones:
        for pk, nombre in Referencia.objects.values_list('pk', 'nombre'):
            referencias.setdefault(clave_referencia(nombre), []).append(pk)
    casos = [When(Q(linea__referencia_id__in=referencias.get(clave, []), subcategoria_id=sub), then=Value(i))
             for clave, d in configuraciones.items() for i, sub in enumerate(d['orden'])]
    return queryset.annotate(_orden_subcategoria=Case(*casos, default=Value(1000000), output_field=IntegerField())).order_by(
        'linea__referencia__nombre', 'linea_id', '_orden_subcategoria', 'orden', 'pk')


def nombre_linea(linea):
    return linea.referencia.nombre if linea.referencia_id else linea.nombre


def categoria_variante(variante):
    if variante.linea.referencia_id and variante.subcategoria_id:
        return variante.subcategoria.categoria
    return variante.categoria_referencia or (variante.categoria if not variante.linea.referencia_id else None)


def datos_referencia(ref):
    return {
        'referencia': ref.pk, 'nombre': ref.nombre,
        'proveedor': ref.proveedor_id, 'proveedor_nombre': ref.proveedor.nombre_empresa,
        'categorias': [{'id': c.pk, 'nombre': c.nombre} for c in ref.categorias.all()],
        'subcategorias': [{'id': s.pk, 'nombre': s.nombre, 'categoria': s.categoria_id, 'categoria_nombre': s.categoria.nombre} for s in ref.subcategorias.all()],
    }


def clasificacion(linea, categoria=None, subcategoria=None):
    """Valida pertenencia sin crear/editar categorías ni tipos de Referencias."""
    if not linea.referencia_id:
        return categoria
    ref = linea.referencia
    subs = list(ref.subcategorias.all())
    if subcategoria is not None and subcategoria.pk not in {s.pk for s in subs}:
        raise ValidationError({'subcategoria': 'El tipo debe pertenecer a esta referencia.'})
    permitidas = {c.pk: c for c in ref.categorias.all()}
    permitidas.update({s.categoria_id: s.categoria for s in subs})
    if subcategoria is not None:
        if categoria is not None and categoria.pk != subcategoria.categoria_id:
            raise ValidationError({'categoria': 'La categoría debe corresponder al tipo de producto.'})
        return subcategoria.categoria
    if categoria is not None and categoria.pk not in permitidas:
        raise ValidationError({'categoria': 'La categoría debe pertenecer a esta referencia.'})
    return categoria or (next(iter(permitidas.values())) if len(permitidas) == 1 else None)


def subcategoria_pedida(valor):
    """La subcategoría que pide el navegador (vacía = todas)."""
    if valor in (None, ''):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValidationError({'subcategoria': 'Subcategoría inválida.'})


@transaction.atomic
def crear_configuracion(referencia, subcategoria=None, **datos):
    # Bloquear no modifica la referencia; impide dos configuraciones simultáneas.
    Referencia.objects.select_for_update().get(pk=referencia.pk)
    if LineaProducto.objects.filter(referencia=referencia).exists():
        raise ValidationError({'referencia': 'Esta referencia ya tiene su lista de precios.'})
    try:
        with transaction.atomic():
            linea = LineaProducto.objects.create(referencia=referencia, nombre=referencia.nombre[:150],
                                                  slug=f'referencia-{referencia.pk}', **datos)
            sincronizar_subcategorias(linea, subcategoria)
            return linea
    except IntegrityError:
        raise ValidationError({'referencia': 'Esta referencia ya tiene una configuración. Actualiza la lista.'})


@transaction.atomic
def sincronizar_subcategorias(linea, subcategoria=None):
    """Una ficha de costos por tipo asignado; nunca modifica el catálogo maestro.

    Con `subcategoria` (el «Agregar costos» de una fila) crea solo esa ficha; sin ella, todas."""
    LineaProducto.objects.select_for_update().get(pk=linea.pk)
    if not linea.referencia_id:
        raise ValidationError('Esta configuración no está vinculada a una referencia.')
    actuales = list(VarianteProducto.objects.filter(linea_id=linea.pk))
    subs = list(linea.referencia.subcategorias.select_related('categoria').order_by('categoria__nombre', 'nombre', 'pk'))
    ids = {s.pk for s in subs}
    if any(v.subcategoria_id not in ids for v in actuales):
        raise ValidationError('Hay precios de subcategorías retiradas de la referencia. Revisa su clasificación antes de continuar.')
    if subcategoria is not None:
        if subcategoria not in ids:
            raise ValidationError({'subcategoria': 'Esta subcategoría no pertenece a la referencia.'})
        subs = [s for s in subs if s.pk == subcategoria]
    existentes = {v.subcategoria_id for v in actuales}
    orden = max((v.orden for v in actuales), default=-1) + 1
    nuevas = [VarianteProducto(linea=linea, subcategoria=s, categoria_referencia=s.categoria,
                              nombre=s.nombre, orden=orden + i, costo_base=0, costo_confirmado=False)
              for i, s in enumerate(s for s in subs if s.pk not in existentes)]
    VarianteProducto.objects.bulk_create(nuevas)
    if nuevas:
        LineaProducto.objects.filter(pk=linea.pk).update(activo=False)
        linea.activo = False
        from .cache_catalogo import invalidar
        invalidar()
    return nuevas
