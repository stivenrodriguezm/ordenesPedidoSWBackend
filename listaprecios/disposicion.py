"""Presentación comercial compartida: orden y bajas reversibles, sin borrar maestros."""
import unicodedata

from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError

from ordenes.models import Referencia
from suministros.models import Categoria, Subcategoria
from .models import DisposicionReferenciaPrecio


def clave_referencia(nombre):
    texto = unicodedata.normalize('NFD', nombre or '')
    return ' '.join(''.join(c for c in texto if not '\u0300' <= c <= '\u036f').lower().split())


def mapa_disposiciones():
    return {d.clave: {'orden': d.orden, 'retiradas': d.retiradas, 'revision': d.revision}
            for d in DisposicionReferenciaPrecio.objects.all()}


def disposicion(nombre, mapa=None):
    return (mapa if mapa is not None else mapa_disposiciones()).get(
        clave_referencia(nombre), {'orden': [], 'retiradas': [], 'revision': 0})


def retirada(variante, mapa=None):
    return bool(variante.linea.referencia_id and variante.subcategoria_id in
                disposicion(variante.linea.referencia.nombre, mapa)['retiradas'])


def variantes_visibles(linea, mapa=None):
    variantes = list(linea.variantes.all())
    if not linea.referencia_id:
        return variantes
    config = disposicion(linea.referencia.nombre, mapa)
    posiciones = {pk: i for i, pk in enumerate(config['orden'])}
    return sorted((v for v in variantes if v.subcategoria_id not in config['retiradas']),
                  key=lambda v: (posiciones.get(v.subcategoria_id, len(posiciones)), v.orden, v.pk))


class DisposicionDesactualizada(APIException):
    status_code = 409
    default_detail = 'Las subcategorías cambiaron en otra sesión. Actualiza la lista y vuelve a intentarlo.'


@transaction.atomic
def guardar_disposicion(referencia, revision, orden=None, retiradas=None, orden_parcial=None):
    clave = clave_referencia(referencia.nombre)
    ids = [pk for pk, nombre in Referencia.objects.values_list('pk', 'nombre') if clave_referencia(nombre) == clave]
    # Un bloqueo estable aun cuando todavía no existe una disposición guardada.
    list(Referencia.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    actual = DisposicionReferenciaPrecio.objects.select_for_update().filter(clave=clave).first()
    if revision != (actual.revision if actual else 0):
        raise DisposicionDesactualizada()
    subs = list(Subcategoria.objects.filter(referencias__pk__in=ids).distinct().order_by('categoria__nombre', 'nombre', 'pk'))
    permitidas = {s.pk for s in subs}
    bajas = list(retiradas if retiradas is not None else actual.retiradas if actual else [])
    if len(bajas) != len(set(bajas)) or not set(bajas) <= permitidas:
        raise ValidationError({'retiradas': 'Selecciona subcategorías de esta referencia, sin repetirlas.'})
    anteriores = [pk for pk in (actual.orden if actual else []) if pk in permitidas]
    anteriores += [s.pk for s in subs if s.pk not in anteriores]
    visibles = permitidas - set(bajas)
    if orden_parcial is not None:
        cambios = iter(orden_parcial)
        orden = [next(cambios) if pk in orden_parcial else pk for pk in anteriores if pk in visibles]
    nuevos = list(orden if orden is not None else [pk for pk in anteriores if pk in visibles])
    if len(nuevos) != len(set(nuevos)) or set(nuevos) != visibles:
        raise ValidationError({'orden': 'Envía todas las subcategorías visibles de esta referencia, sin repetirlas.'})
    if actual is None:
        actual = DisposicionReferenciaPrecio(clave=clave)
    actual.orden = nuevos + [pk for pk in anteriores if pk not in visibles]
    actual.retiradas, actual.revision = bajas, revision + 1
    actual.save()
    return {'orden': actual.orden, 'retiradas': bajas, 'revision': actual.revision, 'referencias': ids}


@transaction.atomic
def renombrar_subcategoria(pk, nombre):
    sub = Subcategoria.objects.get(pk=pk)
    Categoria.objects.select_for_update().get(pk=sub.categoria_id)
    nombre = nombre.strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError({'nombre': 'Escribe un nombre de 1 a 100 caracteres.'})
    if Subcategoria.objects.filter(categoria_id=sub.categoria_id, nombre__iexact=nombre).exclude(pk=pk).exists():
        raise ValidationError({'nombre': 'Ya existe otra subcategoría con ese nombre en la misma categoría.'})
    sub.nombre = nombre
    sub.save(update_fields=['nombre'])
    return {'id': sub.pk, 'nombre': nombre, 'categoria': sub.categoria_id,
            'referencias_uso': Referencia.objects.filter(subcategorias=sub).count()}


def excluir_retiradas(queryset):
    from django.db.models import Q
    configuraciones = {k: c for k, c in mapa_disposiciones().items() if c['retiradas']}
    if not configuraciones:
        return queryset
    refs = {}
    for pk, nombre in Referencia.objects.values_list('pk', 'nombre'):
        refs.setdefault(clave_referencia(nombre), []).append(pk)
    bajas = Q()
    for clave, config in configuraciones.items():
        bajas |= Q(linea__referencia_id__in=refs.get(clave, []), subcategoria_id__in=config['retiradas'])
    return queryset.exclude(bajas)
