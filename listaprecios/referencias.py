"""Identidad y clasificación del catálogo: siempre las Referencias existentes."""
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from ordenes.models import Referencia
from .models import LineaProducto


def nombre_linea(linea):
    return linea.referencia.nombre if linea.referencia_id else linea.nombre


def categoria_variante(variante):
    return variante.categoria_referencia or (variante.categoria if not variante.linea.referencia_id else None)


def datos_referencia(ref):
    return {
        'referencia': ref.pk, 'nombre': ref.nombre,
        'proveedor': ref.proveedor_id, 'proveedor_nombre': ref.proveedor.nombre_empresa,
        'categorias': [{'id': c.pk, 'nombre': c.nombre} for c in ref.categorias.all()],
        'subcategorias': [{'id': s.pk, 'nombre': s.nombre, 'categoria': s.categoria_id} for s in ref.subcategorias.all()],
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


@transaction.atomic
def crear_configuracion(referencia, **datos):
    # Bloquear no modifica la referencia; impide dos configuraciones simultáneas.
    Referencia.objects.select_for_update().get(pk=referencia.pk)
    if LineaProducto.objects.filter(referencia=referencia).exists():
        raise ValidationError({'referencia': 'Esta referencia ya tiene su lista de precios.'})
    try:
        with transaction.atomic():
            return LineaProducto.objects.create(referencia=referencia, nombre=referencia.nombre[:150],
                                               slug=f'referencia-{referencia.pk}', **datos)
    except IntegrityError:
        raise ValidationError({'referencia': 'Esta referencia ya tiene una configuración. Actualiza la lista.'})
