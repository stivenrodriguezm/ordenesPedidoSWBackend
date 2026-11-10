"""Opciones operativas de pedidos que no crean fichas en la lista de precios."""
import unicodedata

from suministros.models import Subcategoria


def normalizar(texto):
    return ' '.join(unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower().split())


def es_por_modulos(subcategoria):
    return normalizar(subcategoria.nombre) == 'por modulos' and normalizar(subcategoria.categoria.nombre) in {'sala', 'salas'}


def admite_por_modulos(referencia, subcategoria):
    return es_por_modulos(subcategoria) and subcategoria.categoria_id in {c.pk for c in referencia.categorias.all()}


def opciones_pedido(referencia, contexto):
    opciones = list(referencia.subcategorias.all())
    categorias = {c.pk for c in referencia.categorias.all() if normalizar(c.nombre) in {'sala', 'salas'}}
    if categorias:
        if 'subcategorias_operativas_pedido' not in contexto:
            contexto['subcategorias_operativas_pedido'] = [s for s in Subcategoria.objects.select_related('categoria').filter(nombre__istartswith='Por m') if es_por_modulos(s)]
        ids = {s.pk for s in opciones}
        opciones += [s for s in contexto['subcategorias_operativas_pedido'] if s.categoria_id in categorias and s.pk not in ids]
    return [{'id': s.pk, 'nombre': s.nombre} for s in opciones]
