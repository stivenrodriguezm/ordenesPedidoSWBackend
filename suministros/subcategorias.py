"""Subcategorías propias de cada referencia (decisión del usuario, 2026-11-10).

Cada `Subcategoria` pertenece a una sola `Referencia` (la de un proveedor). Así, renombrarla,
cambiarla de categoría o quitarla desde Administrar lista solo cambia esa referencia, y lo
suyo (precios, pedidos, inventario, facturas y grupos) la sigue porque apunta al mismo registro.
Dos referencias pueden tener subcategorías con el mismo nombre: son registros distintos.
Las listas y filtros que muestran «el catálogo» las agrupan por nombre (`clave_subcategoria`).

Las funciones `mover_registros` y `ajustar_disposicion` reciben los modelos para poder usarse
igual desde la migración que separa las subcategorías compartidas (0007 de suministros).
"""
import unicodedata

from django.db import transaction


def clave_texto(nombre):
    texto = unicodedata.normalize('NFD', nombre or '')
    return ' '.join(''.join(c for c in texto if not '̀' <= c <= 'ͯ').lower().split())


def clave_subcategoria(categoria_id, nombre):
    """Misma categoría y mismo nombre (sin tildes ni mayúsculas) = la misma en listas y filtros."""
    return f'{categoria_id}|{clave_texto(nombre)}'


def mover_registros(modelos, anterior_id, nueva_id, referencia_ids):
    """Pasa a `nueva_id` lo de estas referencias que apuntaba a `anterior_id`."""
    for modelo, campo_ref in modelos:
        modelo.objects.filter(subcategoria_id=anterior_id, **{f'{campo_ref}__in': referencia_ids}).update(subcategoria_id=nueva_id)


def ajustar_disposicion(Disposicion, Referencia, Subcategoria, referencia, anterior_id, nueva_id):
    """Orden y bajas de la lista (por nombre comercial): la nueva toma el lugar de la anterior. Si
    otra referencia del mismo nombre (otro proveedor) sigue usando la anterior, ambas quedan."""
    d = Disposicion.objects.select_for_update().filter(clave=clave_texto(referencia.nombre)).first()
    if d is None:
        return
    hermanas = [r.pk for r in Referencia.objects.all() if clave_texto(r.nombre) == clave_texto(referencia.nombre) and r.pk != referencia.pk]
    sigue = Subcategoria.objects.filter(pk=anterior_id, referencias__pk__in=hermanas).exists()

    def cambiar(lista):
        salida = []
        for x in lista:
            if x == anterior_id:
                salida += [x, nueva_id] if sigue else [nueva_id]
            elif x != nueva_id:
                salida.append(x)
        return salida
    orden, retiradas = cambiar(d.orden), cambiar(d.retiradas)
    if (orden, retiradas) != (d.orden, d.retiradas):
        d.orden, d.retiradas, d.revision = orden, retiradas, d.revision + 1
        d.save(update_fields=['orden', 'retiradas', 'revision'])


def _modelos():
    from listaprecios.models import VarianteProducto
    from ordenes.models import DetallePedido
    from suministros.models import DetalleFactura, GrupoInventarioComponente, Inventario
    return [(VarianteProducto, 'linea__referencia_id'), (DetallePedido, 'referencia_id'), (Inventario, 'referencia_id'),
            (DetalleFactura, 'referencia_id'), (GrupoInventarioComponente, 'referencia_id')]


def es_compartida(sub, referencia):
    return sub.referencias.exclude(pk=referencia.pk).exists()


@transaction.atomic
def separar(sub, referencia, nombre=None, categoria_id=None):
    """Copia propia de `sub` para `referencia` (con otro nombre o categoría si se indican) y lleva
    allí todo lo de esa referencia. La subcategoría original queda para las demás referencias."""
    from listaprecios.models import DisposicionReferenciaPrecio
    from ordenes.models import Referencia
    from suministros.models import Subcategoria
    nueva = Subcategoria.objects.create(categoria_id=categoria_id or sub.categoria_id, nombre=nombre or sub.nombre)
    referencia.subcategorias.remove(sub)
    referencia.subcategorias.add(nueva)
    mover_registros(_modelos(), sub.pk, nueva.pk, [referencia.pk])
    ajustar_disposicion(DisposicionReferenciaPrecio, Referencia, Subcategoria, referencia, sub.pk, nueva.pk)
    return nueva


def propia(referencia, sub):
    """La subcategoría de `referencia` equivalente a `sub`: la misma si nadie más la usa; si no, la
    que la referencia ya tenga con ese nombre y categoría, o una copia nueva para ella."""
    if not sub.referencias.exclude(pk=referencia.pk).exists():
        return sub
    clave = clave_subcategoria(sub.categoria_id, sub.nombre)
    for s in referencia.subcategorias.all():
        if s.pk != sub.pk and clave_subcategoria(s.categoria_id, s.nombre) == clave and not es_compartida(s, referencia):
            return s
    if referencia.subcategorias.filter(pk=sub.pk).exists():
        return separar(sub, referencia)
    from suministros.models import Subcategoria
    return Subcategoria.objects.create(categoria_id=sub.categoria_id, nombre=sub.nombre)


@transaction.atomic
def asignar(referencia, subcategorias):
    """Deja a la referencia exactamente estas subcategorías (por nombre y categoría), cada una propia.
    Elegir del catálogo una que usa otra referencia le crea su copia; las que quita, se desasignan."""
    from suministros.models import Subcategoria
    pedidas = list(Subcategoria.objects.filter(pk__in=[getattr(s, 'pk', s) for s in subcategorias]))
    actuales = {s.pk: s for s in referencia.subcategorias.all()}
    claves_actuales = {clave_subcategoria(s.categoria_id, s.nombre): s for s in actuales.values()}
    finales = []
    for sub in pedidas:
        ya = actuales.get(sub.pk) or claves_actuales.get(clave_subcategoria(sub.categoria_id, sub.nombre))
        finales.append(ya if ya is not None and not es_compartida(ya, referencia) else propia(referencia, ya or sub))
    ids = {s.pk for s in finales}
    referencia.subcategorias.remove(*[s for pk, s in actuales.items() if pk not in ids])
    referencia.subcategorias.add(*finales)
    categorias = {s.categoria_id for s in finales}
    if categorias:
        referencia.categorias.add(*categorias)
    return finales


def catalogo_por_nombre(subcategorias):
    """Una entrada por nombre y categoría (para listas y filtros): el primer id y todos los ids."""
    grupos = {}
    for s in subcategorias:
        g = grupos.setdefault(clave_subcategoria(s.categoria_id, s.nombre), {'id': s.pk, 'nombre': s.nombre, 'categoria': s.categoria_id, 'ids': []})
        g['ids'].append(s.pk)
    return list(grupos.values())


def subcategoria_de(referencia_id, subcategoria_id):
    """La subcategoría que corresponde a esta referencia: si la elegida es de otra referencia y esta
    tiene la suya con el mismo nombre y categoría, la suya (los formularios eligen por nombre)."""
    if not referencia_id or not subcategoria_id:
        return subcategoria_id
    from ordenes.models import Referencia
    from suministros.models import Subcategoria
    if Referencia.subcategorias.through.objects.filter(referencia_id=referencia_id, subcategoria_id=subcategoria_id).exists():
        return subcategoria_id
    sub = Subcategoria.objects.filter(pk=subcategoria_id).first()
    if sub is None:
        return subcategoria_id
    clave = clave_subcategoria(sub.categoria_id, sub.nombre)
    propia = next((s.pk for s in Subcategoria.objects.filter(referencias__pk=referencia_id, categoria_id=sub.categoria_id)
                   if clave_subcategoria(s.categoria_id, s.nombre) == clave), None)
    return propia or subcategoria_id


class SubcategoriaDeSuReferencia:
    """Mezcla para modelos con `referencia` y `subcategoria`: al guardar, la de su referencia."""

    def save(self, *args, **kwargs):
        self.subcategoria_id = subcategoria_de(self.referencia_id, self.subcategoria_id)
        return super().save(*args, **kwargs)
