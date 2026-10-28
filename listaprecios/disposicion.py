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


def referencias_del_grupo(referencia):
    """Las referencias que Administrar lista muestra juntas («Referencia · Valencia»): mismo nombre."""
    clave = clave_referencia(referencia.nombre)
    return [r for r in Referencia.objects.all() if clave_referencia(r.nombre) == clave]


def _usos_fuera(sub, refs):
    """¿La subcategoría se usa fuera de estas referencias? (otra referencia, sus precios, pedidos,
    inventario, facturas, remisiones o grupos de inventario)."""
    from ordenes.models import DetallePedido
    from suministros.models import DetalleFactura, GrupoInventario, GrupoInventarioComponente, Inventario, RemisionItemManual
    from .models import VarianteProducto
    ids = [r.pk for r in refs]
    if sub.referencias.exclude(pk__in=ids).exists():  # related_name del M2M de Referencia
        return True
    if VarianteProducto.objects.filter(subcategoria=sub).exclude(linea__referencia_id__in=ids).exists():
        return True
    if GrupoInventario.objects.filter(subcategoria=sub).exists():
        return True
    for modelo in (DetallePedido, Inventario, DetalleFactura, GrupoInventarioComponente):
        if modelo.objects.filter(subcategoria=sub).exclude(referencia_id__in=ids).exists():
            return True
    # En las remisiones manuales la referencia es texto.
    return RemisionItemManual.objects.filter(subcategoria=sub).exclude(referencia__iexact=refs[0].nombre).exists()


def _mover_subcategoria(anterior, nueva, refs):
    """Pasa estas referencias (y lo suyo: precios, pedidos, inventario, facturas, remisiones y la
    disposición de la lista) de una subcategoría a otra. Lo de las demás referencias no cambia."""
    from ordenes.models import DetallePedido
    from suministros.models import DetalleFactura, GrupoInventarioComponente, Inventario, RemisionItemManual
    from .cache_catalogo import invalidar
    from .models import VarianteProducto
    ids = [r.pk for r in refs]
    for r in refs:
        r.subcategorias.remove(anterior)
        r.subcategorias.add(nueva)
        r.categorias.add(nueva.categoria_id)
    VarianteProducto.objects.filter(subcategoria=anterior, linea__referencia_id__in=ids).update(subcategoria=nueva, nombre=nueva.nombre)
    for modelo in (DetallePedido, Inventario, DetalleFactura, GrupoInventarioComponente):
        modelo.objects.filter(subcategoria=anterior, referencia_id__in=ids).update(subcategoria=nueva)
    RemisionItemManual.objects.filter(subcategoria=anterior, referencia__iexact=refs[0].nombre).update(subcategoria=nueva)
    clave = clave_referencia(refs[0].nombre)
    d = DisposicionReferenciaPrecio.objects.select_for_update().filter(clave=clave).first()
    if d:
        cambiar = lambda lista: list(dict.fromkeys(nueva.pk if x == anterior.pk else x for x in lista))
        d.orden, d.retiradas = cambiar(d.orden), cambiar(d.retiradas)
        d.revision += 1
        d.save(update_fields=['orden', 'retiradas', 'revision'])
    invalidar()


@transaction.atomic
def renombrar_subcategoria(pk, nombre, referencia=None):
    """(2026-10-28) Las subcategorías van asociadas a la referencia: renombrar desde una referencia
    solo cambia esa referencia (y las que la lista muestra con ella). Si otra referencia usa la misma
    subcategoría, esta pasa a una propia con el nombre nuevo (o a la que ya exista con ese nombre en
    la categoría); si nadie más la usa, se renombra tal cual."""
    sub = Subcategoria.objects.get(pk=pk)
    Categoria.objects.select_for_update().get(pk=sub.categoria_id)
    nombre = nombre.strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError({'nombre': 'Escribe un nombre de 1 a 100 caracteres.'})
    if referencia is None:
        refs = list(Referencia.objects.filter(subcategorias=sub))
    else:
        refs = [r for r in referencias_del_grupo(referencia) if r.subcategorias.filter(pk=sub.pk).exists()]
        if not refs:
            raise ValidationError({'nombre': 'Esta subcategoría no pertenece a la referencia.'})
    existente = Subcategoria.objects.filter(categoria_id=sub.categoria_id, nombre__iexact=nombre).exclude(pk=pk).first()
    if existente is None and (referencia is None or not _usos_fuera(sub, refs)):
        sub.nombre = nombre
        sub.save(update_fields=['nombre'])
        from .models import VarianteProducto
        VarianteProducto.objects.filter(subcategoria=sub, linea__referencia__isnull=False).update(nombre=nombre)
        from .cache_catalogo import invalidar
        invalidar()
        destino = sub
    else:
        if referencia is None:
            raise ValidationError({'nombre': 'Ya existe otra subcategoría con ese nombre en la misma categoría.'})
        if existente is not None and any(r.subcategorias.filter(pk=existente.pk).exists() for r in refs):
            raise ValidationError({'nombre': f'Esta referencia ya tiene la subcategoría «{existente.nombre}».'})
        destino = existente or Subcategoria.objects.create(categoria_id=sub.categoria_id, nombre=nombre)
        _mover_subcategoria(sub, destino, refs)
    return {'id': destino.pk, 'anterior': sub.pk, 'nombre': destino.nombre, 'categoria': destino.categoria_id,
            'separada': destino.pk != sub.pk, 'referencias': [r.pk for r in refs],
            'referencias_uso': Referencia.objects.filter(subcategorias=destino).count()}


@transaction.atomic
def agregar_subcategoria_nueva(referencia, nombre, categoria, todas=False):
    """Agrega a la referencia (o a todas las de su grupo) una subcategoría con este nombre: usa la
    del catálogo si ya existe en la categoría; si no, la crea. Si estaba retirada de la lista, vuelve."""
    nombre = (nombre or '').strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError({'nombre': 'Escribe un nombre de 1 a 100 caracteres.'})
    Categoria.objects.select_for_update().get(pk=categoria.pk)
    sub = Subcategoria.objects.filter(categoria=categoria, nombre__iexact=nombre).first()
    refs = referencias_del_grupo(referencia) if todas else [referencia]
    if sub and all(r.subcategorias.filter(pk=sub.pk).exists() for r in refs):
        raise ValidationError({'nombre': f'La referencia ya tiene la subcategoría «{sub.nombre}».'})
    sub = sub or Subcategoria.objects.create(categoria=categoria, nombre=nombre)
    for r in refs:
        r.subcategorias.add(sub)
        r.categorias.add(categoria)
    d = DisposicionReferenciaPrecio.objects.select_for_update().filter(clave=clave_referencia(referencia.nombre)).first()
    if d and sub.pk in d.retiradas:
        d.retiradas = [x for x in d.retiradas if x != sub.pk]
        d.revision += 1
        d.save(update_fields=['retiradas', 'revision'])
    from .cache_catalogo import invalidar
    invalidar()
    return {'id': sub.pk, 'nombre': sub.nombre, 'categoria': categoria.pk, 'referencias': [r.pk for r in refs]}


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
