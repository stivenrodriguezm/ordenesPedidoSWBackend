"""Lógica de negocio del módulo Lista de Precios — mantenida fuera de
views.py/serializers.py según INSTRUCCIONES_PROYECTO.md (Fat Models/Thin
Views). El motor de cálculo reemplaza las 2.181 fórmulas de lista2026.xlsx
por una sola función, testeable (ver tests.py)."""
from decimal import Decimal

from django.db import transaction

from .models import GrupoTela, Multiplicador, VarianteProducto, PrecioVariante


def obtener_grupos_tela():
    """Todos los grupos de tela/cuero, en orden — cada uno ya trae su
    propio precio_por_metro (es el mismo sin importar la categoría del
    producto, ver GrupoTela.precio_por_metro). Se precarga una sola vez por
    request (es una tabla pequeña) y se pasa a precios_por_variante() para
    la variante sin PrecioVariante propios (ver su docstring) — evita una
    consulta repetida por cada variante al serializar listas completas."""
    return list(GrupoTela.objects.order_by('orden'))


def obtener_multiplicador_general():
    """El Multiplicador marcado es_general=True — el que usan por defecto
    casi todas las variantes (multiplicador nulo). Si por algún motivo no
    hay ninguno marcado (no debería pasar — el admin siempre debe tener
    exactamente uno), cae a ×1 en vez de reventar el cálculo de precios."""
    general = Multiplicador.objects.filter(es_general=True).first()
    return general.valor if general else Decimal('1')


def multiplicador_efectivo(variante, multiplicador_general=None):
    """El multiplicador que realmente aplica a esta variante: el suyo
    propio si tiene uno asignado, o el general del catálogo si no.

    `multiplicador_general`: valor opcional ya resuelto (de
    obtener_multiplicador_general()) para evitar una consulta repetida al
    calcular precios de muchas variantes en la misma request."""
    if variante.multiplicador_id and variante.multiplicador.valor is not None:
        return variante.multiplicador.valor
    if multiplicador_general is not None:
        return multiplicador_general
    return obtener_multiplicador_general()


def calcular_precio(variante, grupo=None, opcionales_ids=None, multiplicador_general=None):
    """Calcula el precio de venta de una variante para un grupo de tela (o
    sin grupo, para productos sin tela).

    precio = (costo_base + metraje_tela × precio_por_metro_del_grupo + cargos_fijos + cargos_opcionales_seleccionados) × multiplicador

    El precio por metro/decímetro sale del grupo mismo
    (GrupoTela.precio_por_metro) — es el mismo sin importar la categoría
    del producto (corrección explícita: antes variaba por categoría, ya no).
    El multiplicador sale de multiplicador_efectivo(): un catálogo de
    multiplicadores con nombre libre, completamente independiente de la
    categoría — casi todas las variantes usan el que esté marcado
    "general", pero cualquiera puede tener el suyo propio, asignado
    individualmente o en bloque (ver asignar_multiplicador_masivo).

    Cargos NO opcionales (ej. costos de instalación internos) siempre se
    suman — son costo, no se exponen al vendedor. Cargos opcionales (ej.
    "Transporte", "Tomacorriente USB") solo se suman si su id viene en
    `opcionales_ids` — son extras de venta que el vendedor activa al
    cotizar. Todos los cargos (fijos y opcionales seleccionados) se suman
    ANTES de multiplicar por el multiplicador, igual que costo_base y el
    metraje de tela — nunca se agregan ya-multiplicados encima.

    Si existe un PrecioVariante para (variante, grupo) con precio_manual no
    nulo, ese valor fijo se usa como base en vez de la fórmula — pero los
    cargos opcionales seleccionados se siguen sumando encima (multiplicados
    igual que en el caso normal: (base/mult + opcionales) × mult == base +
    opcionales×mult, así que sumarlos ya-multiplicados al final da el mismo
    resultado sin tener que "desarmar" el precio fijado a mano).

    `multiplicador_general`: valor opcional ya resuelto (de
    obtener_multiplicador_general()) para evitar una consulta por cada
    llamada — se recomienda siempre que se calculen precios de varias
    variantes en la misma request (ver precios_por_variante). Sin él, cae a
    una consulta directa (correcto pero más lento) — válido para cálculos
    puntuales aislados.
    """
    multiplicador = multiplicador_efectivo(variante, multiplicador_general)
    opcionales_ids = set(opcionales_ids) if opcionales_ids else set()
    cargos_opcionales = sum(
        (c.valor for c in variante.cargos.all() if c.opcional and c.id in opcionales_ids), Decimal('0')
    )

    grupo_id = grupo.id if grupo is not None else None
    override = next((p for p in variante.precios.all() if p.grupo_id == grupo_id), None)
    if override is not None and override.precio_manual is not None:
        return override.precio_manual + cargos_opcionales * multiplicador

    metros_costo = Decimal('0')
    if variante.metraje_tela and grupo is not None:
        metros_costo = variante.metraje_tela * (grupo.precio_por_metro or Decimal('0'))

    cargos_fijos = sum((c.valor for c in variante.cargos.all() if not c.opcional), Decimal('0'))

    return (variante.costo_base + metros_costo + cargos_fijos + cargos_opcionales) * multiplicador


def opcionales_de_variante(variante):
    """Cargos opcionales de una variante — {id, descripcion, valor} — lo
    único de CargoVariante que es seguro exponer al vendedor (son extras de
    venta, no costo interno; ver docstring de CargoVariante)."""
    return [
        {'id': c.id, 'descripcion': c.descripcion, 'valor': c.valor}
        for c in variante.cargos.all() if c.opcional
    ]


def precios_por_variante(variante, grupos=None, multiplicador_general=None):
    """Devuelve [{grupo, grupo_nombre, precio}, ...] para todos los grupos
    de tela aplicables a una variante (o una sola fila con grupo=None si el
    producto no lleva tela).

    Si la variante no tiene PrecioVariante propios, se calcula un precio
    para CADA grupo del catálogo — todos aplican por igual a cualquier
    producto, ya no depende de la categoría. `grupos`: lista opcional ya
    resuelta (de obtener_grupos_tela()) para evitar una consulta repetida
    por variante al serializar listas completas."""
    filas = list(variante.precios.all())
    if not filas:
        if variante.metraje_tela:
            todos_grupos = grupos if grupos is not None else obtener_grupos_tela()
            return [
                {'grupo': g.id, 'grupo_nombre': g.nombre, 'precio': calcular_precio(variante, g, multiplicador_general=multiplicador_general)}
                for g in todos_grupos
            ]
        return [{'grupo': None, 'grupo_nombre': None, 'precio': calcular_precio(variante, None, multiplicador_general=multiplicador_general)}]

    resultado = []
    for fila in filas:
        resultado.append({
            'grupo': fila.grupo_id,
            'grupo_nombre': fila.grupo.nombre if fila.grupo else None,
            'precio': calcular_precio(variante, fila.grupo, multiplicador_general=multiplicador_general),
        })
    return resultado


def impacto_categoria(categoria):
    """Vista previa de impacto antes de desactivar/borrar una categoría —
    ya no afecta ningún precio (el precio por grupo es global), solo
    cuántas líneas/variantes quedarían sin esa etiqueta de tipo de mueble."""
    variantes = categoria.variantes.filter(linea__activo=True)
    lineas_afectadas = variantes.values_list('linea_id', flat=True).distinct().count()
    return {
        'lineas_afectadas': lineas_afectadas,
        'variantes_afectadas': variantes.count(),
    }


def impacto_grupo_tela(grupo):
    """Cuántas variantes tienen un precio manual fijado para este grupo en
    concreto (se pierde si se elimina, la relación es CASCADE) — además,
    como el precio de este grupo aplica a cualquier producto con tela que
    no tenga overrides propios, eliminarlo también le quita esa opción de
    grupo a todo ese resto del catálogo."""
    return {
        'precios_variante_afectados': PrecioVariante.objects.filter(grupo=grupo).count(),
    }


def impacto_multiplicador(multiplicador):
    """Cuántas variantes se ven afectadas por un cambio en el VALOR de este
    multiplicador: las asignadas directamente, más — si es el general — las
    que no tienen uno propio (multiplicador nulo, la inmensa mayoría del
    catálogo)."""
    directas = VarianteProducto.objects.filter(multiplicador=multiplicador, linea__activo=True)
    if multiplicador.es_general:
        heredadas = VarianteProducto.objects.filter(multiplicador__isnull=True, linea__activo=True)
        total = directas.count() + heredadas.count()
    else:
        total = directas.count()
    return {'variantes_afectadas': total}


@transaction.atomic
def establecer_multiplicador_general(multiplicador):
    """Marca `multiplicador` como el general y desmarca cualquier otro —
    solo puede haber uno a la vez (es lo que usan por defecto todas las
    variantes con multiplicador nulo)."""
    Multiplicador.objects.exclude(pk=multiplicador.pk).filter(es_general=True).update(es_general=False)
    if not multiplicador.es_general:
        multiplicador.es_general = True
        multiplicador.save(update_fields=['es_general'])


def asignar_multiplicador_masivo(multiplicador_id, categoria_id=None, linea_id=None, variante_ids=None):
    """Asigna (o quita, si multiplicador_id es None → "usar el general") un
    multiplicador a muchas variantes de una sola vez — "por producto,
    categoría y así" — filtrando por categoría, por línea/colección, o por
    una lista explícita de ids. Al menos uno de los tres filtros es
    obligatorio (nunca se actualiza el catálogo completo por accidente)."""
    if not categoria_id and not linea_id and not variante_ids:
        raise ValueError('Se requiere categoria_id, linea_id o variante_ids.')

    qs = VarianteProducto.objects.all()
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)
    if linea_id:
        qs = qs.filter(linea_id=linea_id)
    if variante_ids:
        qs = qs.filter(id__in=variante_ids)

    return qs.update(multiplicador_id=multiplicador_id)
