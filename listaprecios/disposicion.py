"""Presentación comercial compartida: orden y bajas reversibles, sin borrar maestros."""
import unicodedata

from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError

from ordenes.models import Referencia
from suministros.models import Subcategoria
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


def referencias_del_grupo(referencia):
    """Las referencias que Administrar lista muestra juntas («Referencia · Valencia»): mismo nombre."""
    clave = clave_referencia(referencia.nombre)
    return [r for r in Referencia.objects.all() if clave_referencia(r.nombre) == clave]


def _de_la_referencia(sub, referencia, campo):
    if referencia is None or not referencia.subcategorias.filter(pk=sub.pk).exists():
        raise ValidationError({campo: 'Esta subcategoría no pertenece a la referencia.'})


def _repetida(referencia, categoria_id, nombre, excluir):
    """¿La referencia ya tiene otra subcategoría con ese nombre en esa categoría?"""
    from suministros.subcategorias import clave_subcategoria
    clave = clave_subcategoria(categoria_id, nombre)
    return next((s for s in referencia.subcategorias.exclude(pk=excluir) if clave_subcategoria(s.categoria_id, s.nombre) == clave), None)


def _invalidar():
    from .cache_catalogo import invalidar
    invalidar()


@transaction.atomic
def renombrar_subcategoria(pk, nombre, referencia=None):
    """(2026-11-10) Las subcategorías son propias de cada referencia (de un proveedor): renombrar
    solo cambia esa referencia, sin restricciones por otras referencias ni fusiones con otras
    subcategorías del mismo nombre. Si aún la compartía con otra, primero se le separa una propia."""
    from suministros.subcategorias import es_compartida, separar
    sub = Subcategoria.objects.select_for_update().get(pk=pk)
    nombre = (nombre or '').strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError({'nombre': 'Escribe un nombre de 1 a 100 caracteres.'})
    if referencia is None:
        # Sin referencia (API anterior): solo si la subcategoría es de una sola referencia.
        duenas = list(sub.referencias.all()[:2])
        if len(duenas) > 1:
            raise ValidationError({'nombre': 'Indica la referencia: esta subcategoría la usan varias.'})
        referencia = duenas[0] if duenas else None
    if referencia is not None:
        _de_la_referencia(sub, referencia, 'nombre')
    otra = referencia and _repetida(referencia, sub.categoria_id, nombre, sub.pk)
    if otra is not None:
        raise ValidationError({'nombre': f'Esta referencia ya tiene la subcategoría «{otra.nombre}».'})
    if referencia is not None and es_compartida(sub, referencia):
        destino = separar(sub, referencia, nombre=nombre)
    else:
        sub.nombre = nombre
        sub.save(update_fields=['nombre'])
        destino = sub
    from .models import VarianteProducto
    VarianteProducto.objects.filter(subcategoria=destino, linea__referencia__isnull=False).update(nombre=nombre)
    _invalidar()
    return {'id': destino.pk, 'anterior': sub.pk, 'nombre': destino.nombre, 'categoria': destino.categoria_id,
            'separada': destino.pk != sub.pk, 'referencias': [referencia.pk] if referencia else []}


@transaction.atomic
def cambiar_categoria_subcategoria(pk, categoria, referencia):
    """(2026-11-10) Cambia la categoría solo en esta referencia. Lo suyo que guarda la categoría
    (inventario, facturas, remisiones, grupos y la ficha de precios) la acompaña."""
    from suministros.subcategorias import es_compartida, separar
    sub = Subcategoria.objects.select_for_update().select_related('categoria').get(pk=pk)
    if sub.categoria_id == categoria.pk:
        raise ValidationError({'categoria': f'«{sub.nombre}» ya está en {categoria.nombre}.'})
    _de_la_referencia(sub, referencia, 'categoria')
    otra = _repetida(referencia, categoria.pk, sub.nombre, sub.pk)
    if otra is not None:
        raise ValidationError({'categoria': f'Esta referencia ya tiene «{otra.nombre}» en {categoria.nombre}.'})
    anterior = sub.categoria
    if es_compartida(sub, referencia):
        destino = separar(sub, referencia, categoria_id=categoria.pk)
    else:
        sub.categoria = categoria
        sub.save(update_fields=['categoria'])
        destino = sub
    _seguir_categoria(destino, [referencia])
    referencia.categorias.add(categoria)
    if not referencia.subcategorias.filter(categoria=anterior).exists():
        referencia.categorias.remove(anterior)
    _invalidar()
    return {'id': destino.pk, 'anterior': sub.pk, 'nombre': destino.nombre, 'categoria': categoria.pk,
            'categoria_nombre': categoria.nombre, 'separada': destino.pk != sub.pk, 'referencias': [referencia.pk]}


def _seguir_categoria(sub, refs):
    """Los registros de estas referencias con la subcategoría quedan en su categoría."""
    from suministros.models import DetalleFactura, GrupoInventarioComponente, Inventario, RemisionItemManual
    from .models import VarianteProducto
    ids = [r.pk for r in refs]
    VarianteProducto.objects.filter(subcategoria=sub, linea__referencia_id__in=ids, categoria_referencia__isnull=False).update(categoria_referencia=sub.categoria_id)
    for modelo in (Inventario, DetalleFactura, GrupoInventarioComponente):
        modelo.objects.filter(subcategoria=sub, referencia_id__in=ids).update(categoria=sub.categoria_id)
    RemisionItemManual.objects.filter(subcategoria=sub, referencia__iexact=refs[0].nombre).update(categoria=sub.categoria_id)


@transaction.atomic
def agregar_subcategoria_nueva(referencia, nombre, categoria, todas=False):
    """(2026-11-10) Crea una subcategoría propia de la referencia (o una para cada proveedor de su
    grupo con `todas`). Nunca reutiliza la de otra referencia. Si estaba retirada de la lista, vuelve."""
    nombre = (nombre or '').strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError({'nombre': 'Escribe un nombre de 1 a 100 caracteres.'})
    refs = referencias_del_grupo(referencia) if todas else [referencia]
    faltan = [r for r in refs if _repetida(r, categoria.pk, nombre, None) is None]
    if not faltan:
        raise ValidationError({'nombre': f'La referencia ya tiene la subcategoría «{nombre}».'})
    creadas = []
    for r in faltan:
        sub = Subcategoria.objects.create(categoria=categoria, nombre=nombre)
        r.subcategorias.add(sub)
        r.categorias.add(categoria)
        creadas.append(sub)
    _invalidar()
    return {'id': creadas[0].pk, 'ids': [s.pk for s in creadas], 'nombre': nombre, 'categoria': categoria.pk, 'referencias': [r.pk for r in faltan]}


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
