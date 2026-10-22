"""«Cojines incluidos» — cargo fijo «Decorativos x2» (2026-10-15).

Un producto con ese cargo da derecho, por cada unidad, a 2 productos de la línea
Decorativos sin cobro. Se cubren completos en tela de grupo 1 o 2; de grupo 3 en adelante
(o en cuero) se cubre lo que valdría ese mismo decorativo en grupo 2 y se cobra la
diferencia. Si se llevan más decorativos que el cupo, quedan incluidos los de mayor valor
cubierto (lo más favorable para el cliente, que ya pagó esos cojines dentro del producto) y
el resto se cobra completo. Los opcionales de un decorativo siempre se cobran.

Una sola regla para la cotización y para los productos de la venta.
"""
from decimal import Decimal

from django.db.models import Q

from .models import CargoVariante, GrupoTela, LineaProducto, VarianteProducto
from .services import calcular_precio, precios_por_variante

UNIDADES_POR_PRODUCTO = 2
DESCRIPCION = 'Decorativos x2'
SLUG_LINEA = 'decorativos'
NOMBRE_LINEA = 'Decorativos'
GRUPOS_CUBIERTOS = 2  # los dos primeros grupos de tela: Grupo 1 y Grupo 2
CENT = Decimal('0.01')


def grupos_incluidos():
    """Ids de los grupos de tela que el cupo cubre completos (los dos primeros por orden)."""
    return list(GrupoTela.objects.filter(tipo='tela').order_by('orden', 'id').values_list('pk', flat=True)[:GRUPOS_CUBIERTOS])


def linea_decorativos():
    return LineaProducto.objects.filter(slug=SLUG_LINEA).first()


def cargo_decorativos(variante):
    return next((c for c in variante.cargos.all() if c.tipo == CargoVariante.TIPO_DECORATIVOS), None)


def da_decorativos(variante, opcionales=None):
    """El producto trae «Decorativos x2» activo (usa los cargos ya precargados). Obligatorio:
    siempre. Opcional: si viene elegido en `opcionales`; sin selección (None), si está
    habilitado (preseleccionado)."""
    cargo = cargo_decorativos(variante)
    if cargo is None:
        return False
    if not cargo.opcional:
        return True
    return cargo.preseleccionado if opcionales is None else cargo.pk in set(opcionales)


def valor_sugerido():
    """Valor del cargo: el costo de los 2 decorativos que cubre, tomando el de mayor costo en
    el último grupo incluido (hoy Cojín en Grupo 2: 2 × $57.000 = $114.000). Es el mismo para
    todos los productos; se puede editar en cada uno."""
    from .services import costo_lista
    grupos = list(GrupoTela.objects.filter(pk__in=grupos_incluidos()))
    variantes = [v for v in VarianteProducto.objects.filter(
        Q(linea__es_decorativo=True) | Q(linea__slug=SLUG_LINEA)).prefetch_related('cargos', 'componentes')]
    costos = [costo_lista(v, g, []) for v in variantes for g in (grupos or [None])]
    return (UNIDADES_POR_PRODUCTO * max(costos, default=Decimal(0))).quantize(Decimal(1))


def es_decorativo(variante):
    return variante.linea.es_decorativo or variante.linea.slug == SLUG_LINEA


def tope_por_unidad(variante, grupo, incluidos):
    """Lo máximo que el cupo cubre por una unidad de este decorativo (sin opcionales)."""
    filas = {f['grupo']: f['precio'] for f in precios_por_variante(variante)}
    grupo_id = grupo.pk if grupo else None
    precio = filas.get(grupo_id)
    if precio is None:
        precio = calcular_precio(variante, grupo)
    precio = Decimal(precio)
    if grupo is None or grupo_id in incluidos:
        return precio.quantize(CENT)
    referencias = [Decimal(filas[g]) for g in incluidos if filas.get(g) is not None]
    referencia = max(referencias) if referencias else Decimal(0)
    return min(precio, referencia).quantize(CENT)


def elegir_incluidos(cupo, unidades):
    """`unidades` = [(clave, tope)], una por unidad física. Cubre las `cupo` de mayor tope
    (empate: la que aparece primero). Devuelve {clave: {'unidades': n, 'valor': Decimal}}."""
    elegidas = sorted(enumerate(unidades), key=lambda x: (-x[1][1], x[0]))[:max(0, cupo)]
    resultado = {}
    for _, (clave, tope) in elegidas:
        if tope <= 0:
            continue
        r = resultado.setdefault(clave, {'unidades': 0, 'valor': Decimal(0)})
        r['unidades'] += 1
        r['valor'] += tope
    return resultado


def calcular_incluidos(items, incluidos=None):
    """`items` = [{'clave', 'variante', 'grupo', 'cantidad', 'opcionales'?}] (variante con línea y
    cargos precargados, o None; `opcionales` = ids elegidos, si se conocen). Devuelve
    {clave: {'unidades', 'valor'}} de los decorativos cubiertos."""
    cupo = sum(UNIDADES_POR_PRODUCTO * it['cantidad'] for it in items
               if it['variante'] and da_decorativos(it['variante'], it.get('opcionales')))
    decorativos = [it for it in items if it['variante'] and es_decorativo(it['variante'])]
    if not cupo or not decorativos:
        return {}
    incluidos = grupos_incluidos() if incluidos is None else incluidos
    unidades = []
    for it in decorativos:
        tope = tope_por_unidad(it['variante'], it['grupo'], incluidos)
        unidades += [(it['clave'], tope)] * it['cantidad']
    return elegir_incluidos(cupo, unidades)
