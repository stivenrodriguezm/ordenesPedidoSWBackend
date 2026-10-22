"""Lógica de negocio del módulo Lista de Precios — mantenida fuera de
views.py/serializers.py según INSTRUCCIONES_PROYECTO.md (Fat Models/Thin
Views). El motor de cálculo reemplaza las 2.181 fórmulas de lista2026.xlsx
por una sola función, testeable (ver tests.py)."""
from collections import Counter
from copy import copy
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import APIException, ValidationError

from .especiales import admite_grupo, configuracion_cargo, costo_configuracion, precio_configuracion
from .adicionales_componentes import validar_adicionales, tiene_material, admite_material, costo_especial, costo_adicionales, venta_adicionales
from .models import CargoVariante, ComponenteJuego, GrupoTela, LineaProducto, Multiplicador, VarianteProducto, PrecioVariante
from .referencias import categoria_variante, nombre_linea, productos_publicados

# Prefetch para calcular precios de juegos (componentes con sus cargos y precios).
PREFETCH_JUEGOS = ('componentes__variante__cargos__especial', 'componentes__variante__precios',
                   'componentes__variante__multiplicador', 'componentes__variante__subcategoria__categoria', 'componentes__variante__linea__referencia__proveedor', 'componentes__variante__componentes')


def _invalidar_catalogo():
    from .cache_catalogo import invalidar
    invalidar()


def componentes_de(variante):
    """Componentes de un juego (lista vacía si es un producto normal)."""
    precargados = getattr(variante, '_prefetched_objects_cache', {}).get('componentes')
    if precargados is not None:
        return list(precargados)
    return list(variante.componentes.all()) if variante is not None and variante.pk else []


def usa_tela(variante):
    """¿El precio depende del grupo de tela? En un juego, si alguno de sus componentes lleva tela."""
    comps = componentes_de(variante)
    if comps:
        return any(usa_tela(c.variante) or tiene_material(c) for c in comps)
    return bool(variante.metraje_tela or variante.decimetraje_cuero) or any(p.grupo_id for p in variante.precios.all())


def metraje_total(variante, material='tela'):
    comps = componentes_de(variante)
    if comps:
        return sum(((metraje_total(c.variante, material) or Decimal('0')) * c.cantidad for c in comps), Decimal('0'))
    return variante.decimetraje_cuero if material == 'cuero' else variante.metraje_tela


def opcionales_piezas(variante):
    """Cargos opcionales de las piezas de un conjunto: el conjunto los ofrece igual que la
    pieza, porque sus cargos son los mismos del producto original (2026-10-15)."""
    return [(c, cargo) for c in componentes_de(variante) for cargo in c.variante.cargos.all() if cargo.opcional]


def ids_opcionales(variante):
    """Ids de los opcionales que se pueden elegir en una variante (y en las piezas, si es conjunto)."""
    return {c.pk for c in variante.cargos.all() if c.opcional} | {cargo.pk for _, cargo in opcionales_piezas(variante)}


def conteo_opcionales(opcionales):
    """{id: cantidad} de una selección de opcionales: ids (repetidos = varias unidades) o
    {'id', 'cantidad'?} como los guarda la cotización. Ignora lo que no es un id válido."""
    conteo = Counter()
    for item in opcionales or ():
        try:
            if isinstance(item, dict):
                conteo[int(item['id'])] += max(1, int(item.get('cantidad') or 1))
            elif not isinstance(item, bool):
                conteo[int(item)] += 1
        except (KeyError, TypeError, ValueError):
            continue
    return conteo


def ids_preseleccionados(variante):
    """Opcionales «habilitados» (incluidos de entrada) de la variante y de sus piezas. Son los
    que cuentan cuando no se indica una selección: precio de lista, costo total y venta."""
    return ({c.pk for c in variante.cargos.all() if c.opcional and c.preseleccionado}
            | {cargo.pk for _, cargo in opcionales_piezas(variante) if cargo.preseleccionado})


def grupo_aplicable(variante, grupo):
    """Un grupo solo puede usarse si cada pieza tapizada ofrece ese material."""
    filas = list(variante.precios.all())
    propia = next((p for p in filas if p.grupo_id == grupo.pk), None)
    if propia and propia.precio_manual is not None:
        return True
    if filas and propia is None:
        return False
    comps = componentes_de(variante)
    if comps:
        tapizados = [c for c in comps if usa_tela(c.variante) or tiene_material(c)]
        return bool(tapizados) and all((not usa_tela(c.variante) or grupo_aplicable(c.variante, grupo))
                                     and admite_material(c, grupo) for c in tapizados)
    return bool(metraje_total(variante, grupo.tipo))


def resumen_componentes(variante):
    """«1 Mesa de 6 + 6 Silla de comedor» (vacío si no es un juego)."""
    partes = []
    for c in componentes_de(variante):
        especiales = [a['nombre'] for a in c.adicionales if a['tipo'] == 'especial']
        partes.append(f'{c.cantidad} {c.variante.nombre_catalogo}' + (f' ({", ".join(especiales)})' if especiales else ''))
    return ' + '.join(partes)


def obtener_grupos_tela():
    """Todos los grupos de tela/cuero, en orden — cada uno ya trae su
    propio precio_por_metro (es el mismo sin importar la categoría del
    producto, ver GrupoTela.precio_por_metro). Se precarga una sola vez por
    request (es una tabla pequeña) y se pasa a precios_por_variante() para
    la variante sin PrecioVariante propios (ver su docstring) — evita una
    consulta repetida por cada variante al serializar listas completas."""
    return list(GrupoTela.objects.order_by('orden'))


class ConfiguracionPreciosIncompleta(APIException):
    """Sin multiplicador general el precio no se puede calcular con seguridad:
    antes se usaba ×1 en silencio y se vendía al costo (H19)."""
    status_code = 409
    default_detail = {
        'error': 'La lista de precios no tiene multiplicador general. Un administrador debe marcar uno '
                 'en Lista de Precios → Multiplicadores antes de cotizar.'
    }
    default_code = 'sin_multiplicador_general'


def obtener_multiplicador_general():
    """El Multiplicador marcado es_general=True — el que usan por defecto
    casi todas las variantes (multiplicador nulo). Siempre debe existir
    exactamente uno (lo garantizan las vistas); si falta, se bloquea el
    cálculo con un error accionable en vez de caer a ×1."""
    general = Multiplicador.objects.filter(es_general=True).first()
    if general is None or general.valor is None or general.valor <= 0:
        raise ConfiguracionPreciosIncompleta()
    return general.valor


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


DESCUENTO_MAXIMO_DEFECTO = Decimal('25.00')


def tope_descuento(variante):
    """Devuelve el porcentaje tope de descuento permitido para una variante.
    Si la variante tiene descuento_maximo configurado, se usa ese valor;
    en caso contrario, se aplica el 25% por defecto acordado."""
    if variante and getattr(variante, 'descuento_maximo', None) is not None:
        return Decimal(str(variante.descuento_maximo))
    return DESCUENTO_MAXIMO_DEFECTO


def costo_lista(variante, grupo=None, opcionales_ids=None, costo_base_override=None, sin_material=False):
    """Costo estimado de referencia para una variante según la lista de precios:
    costo_base + metraje_tela × precio_por_metro + cargos_fijos + cargos_opcionales.
    Es la base interna de la fórmula de calcular_precio (sin el multiplicador comercial).
    Devuelve None si no hay variante. Sin `opcionales_ids` (None) cuentan los opcionales
    habilitados; una lista (aunque esté vacía) es la selección exacta."""
    if not variante:
        return None

    # Cada opcional puede ir varias veces (p. ej. 2 reclinos): `conteo` = {id: cantidad}.
    conteo = Counter(ids_preseleccionados(variante)) if opcionales_ids is None else conteo_opcionales(opcionales_ids)
    opcionales_ids_set = set(conteo)

    cargos_opcionales = sum(
        (c.valor * conteo[c.id] for c in variante.cargos.all() if c.opcional and c.id in opcionales_ids_set and c.tipo not in (CargoVariante.TIPO_DIFERENCIA_PRECIO, CargoVariante.TIPO_ESPECIAL_CONFIGURABLE)), Decimal('0')
    )

    cargos_opcionales += sum((costo_especial(configuracion_cargo(c), grupo, sin_material) * conteo[c.id]
                              for c in variante.cargos.all() if c.opcional and c.id in opcionales_ids_set
                              and c.tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE), Decimal('0'))

    metros_costo = Decimal('0')
    if grupo is not None and not sin_material:
        metros_costo = (metraje_total(variante, grupo.tipo) or Decimal('0')) * (grupo.precio_por_metro or Decimal('0'))

    cargos_fijos = sum((c.valor for c in variante.cargos.all() if not c.opcional), Decimal('0'))

    comps = componentes_de(variante)
    if comps:  # juego: costo de sus piezas (con sus opcionales elegidos) más sus propios cargos
        # El costo base guardado en un conjunto no cuenta: su costo sale solo de las piezas y cargos.
        partes = sum(((costo_lista(c.variante, grupo if usa_tela(c.variante) else None, list(conteo.elements()), costo_base_override=c.costo_unitario, sin_material=sin_material)
                       + costo_adicionales(c, grupo, sin_material)) * c.cantidad for c in comps), Decimal('0'))
        # Un solo transporte por conjunto: el mayor de sus piezas (o el propio).
        from .transportes import descuento_conjunto, valor_costo
        transportes = [(valor_costo(c.variante, opcionales_ids_set), c.cantidad) for c in comps] + [(valor_costo(variante, opcionales_ids_set), 1)]
        return (partes + cargos_fijos + cargos_opcionales - descuento_conjunto(transportes)).quantize(Decimal('0.01'))

    base = variante.costo_base if costo_base_override is None else costo_base_override
    return (base + metros_costo + cargos_fijos + cargos_opcionales).quantize(Decimal('0.01'))


def validar_descuento_documento(lineas_info, descuento_total):
    """Valida que el descuento total de una cotización no supere el tope permitido.
    El tope del documento es la suma ponderada del tope de cada línea:
    tope_documento = Σ (subtotal_linea × tope_linea / 100).
    Lanza ValidationError con mensaje en español si se excede."""
    descuento_dec = Decimal(str(descuento_total or 0))
    if descuento_dec <= 0:
        return Decimal('0.00')

    tope_acumulado = Decimal('0.00')
    subtotal_acumulado = Decimal('0.00')

    for linea in lineas_info:
        subt = Decimal(str(linea.get('subtotal', 0)))
        variante = linea.get('variante_obj')
        tope_pct = tope_descuento(variante)
        tope_linea = (subt * tope_pct / Decimal('100')).quantize(Decimal('0.01'))
        tope_acumulado += tope_linea
        subtotal_acumulado += subt

    if descuento_dec > tope_acumulado:
        pct_max = (tope_acumulado / subtotal_acumulado * Decimal('100')).quantize(Decimal('0.1')) if subtotal_acumulado > 0 else Decimal('25.0')
        raise ValidationError({
            'descuento': f'El descuento de ${descuento_dec:,.2f} supera el tope máximo permitido de ${tope_acumulado:,.2f} ({pct_max}% de la cotización).'
        })

    return descuento_dec


def _precio_componente(componente, grupo, general, opcionales_ids=None):
    pieza = componente.variante
    de_pieza = {c.pk for c in pieza.cargos.all() if c.opcional}
    propios = [i for i in Counter(opcionales_ids or ()).elements() if i in de_pieza]
    precio = calcular_precio(pieza, grupo if usa_tela(pieza) else None, propios, multiplicador_general=general,
                             multiplicador_override=componente.multiplicador, costo_base_override=componente.costo_unitario,
                             ignorar_precio_manual=componente.costo_unitario is not None or componente.multiplicador is not None)
    multiplo = componente.multiplicador if componente.multiplicador is not None else multiplicador_efectivo(pieza, general)
    precio += venta_adicionales(componente, grupo, multiplo, general)
    if precio < 0:
        raise ValidationError({'adicionales': f'Los especiales dejan el precio de «{pieza.nombre_catalogo}» por debajo de cero.'})
    return precio


def calcular_precio(variante, grupo=None, opcionales_ids=None, multiplicador_general=None, multiplicador_override=None,
                    costo_base_override=None, ignorar_precio_manual=False):
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
    ANTES de multiplicar, salvo los especiales de tipo diferencia_precio:
    estos son diferencias comerciales exactas y se aplican al precio final.
    Las diferencias comerciales no alteran el costo de fabricación.

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
    `multiplicador_override`: valor específico para simular precios sin guardar.
    """
    if multiplicador_override is not None:
        multiplicador = Decimal(str(multiplicador_override))
    else:
        multiplicador = multiplicador_efectivo(variante, multiplicador_general)
    # Sin selección (None) el precio de lista incluye los opcionales habilitados; una lista,
    # aunque esté vacía, es exactamente lo que eligió el vendedor.
    conteo = Counter(ids_preseleccionados(variante)) if opcionales_ids is None else conteo_opcionales(opcionales_ids)
    opcionales_ids = set(conteo)
    cargos_opcionales = sum(
        (c.valor * conteo[c.id] for c in variante.cargos.all() if c.opcional and c.id in opcionales_ids and c.tipo not in (CargoVariante.TIPO_DIFERENCIA_PRECIO, CargoVariante.TIPO_ESPECIAL_CONFIGURABLE)), Decimal('0')
    )

    diferencia = sum((c.valor * conteo[c.id] for c in variante.cargos.all()
                      if c.opcional and c.id in opcionales_ids and c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO), Decimal('0'))

    diferencia += sum((precio_configuracion(configuracion_cargo(c), grupo, multiplicador_general) * conteo[c.id]
                       for c in variante.cargos.all() if c.opcional and c.id in opcionales_ids
                       and c.tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE), Decimal('0'))

    def finalizar(base):
        total = base + diferencia
        if total < 0:
            raise ValidationError({'opcionales': 'La diferencia de los especiales deja el precio por debajo de cero. Revisa las opciones.'})
        return total

    grupo_id = grupo.id if grupo is not None else None
    override = next((p for p in variante.precios.all() if p.grupo_id == grupo_id), None)
    comps = componentes_de(variante)
    # Opcionales de las piezas elegidos en el conjunto (cada uno por la cantidad de su pieza).
    de_piezas = [c for c in comps if opcionales_ids & {x.pk for x in c.variante.cargos.all() if x.opcional}]
    if not ignorar_precio_manual and override is not None and override.precio_manual is not None:
        extra = sum(((_precio_componente(c, grupo, multiplicador_general, conteo) - _precio_componente(c, grupo, multiplicador_general))
                     * c.cantidad for c in de_piezas), Decimal('0'))
        return finalizar(override.precio_manual + cargos_opcionales * multiplicador + extra)

    if comps:
        # Juego: suma de los precios de sus componentes (cada uno con su multiplicador y sus
        # opcionales elegidos) más sus propios cargos y opcionales con el multiplicador del
        # juego. El costo base guardado en un conjunto no cuenta.
        partes = sum((_precio_componente(c, grupo, multiplicador_general, conteo) * c.cantidad for c in comps), Decimal('0'))
        propios = sum((c.valor for c in variante.cargos.all() if not c.opcional), Decimal('0')) + cargos_opcionales
        # Un solo transporte por conjunto (2026-10-21): el mayor entre sus piezas y el propio.
        from .transportes import descuento_conjunto, valor_venta
        transportes = [(valor_venta(c.variante, opcionales_ids, c.multiplicador if c.multiplicador is not None
                                    else multiplicador_efectivo(c.variante, multiplicador_general)), c.cantidad) for c in comps]
        transportes.append((valor_venta(variante, opcionales_ids, multiplicador), 1))
        return finalizar(partes + propios * multiplicador - descuento_conjunto(transportes))

    metros_costo = Decimal('0')
    if grupo is not None:
        metros_costo = (metraje_total(variante, grupo.tipo) or Decimal('0')) * (grupo.precio_por_metro or Decimal('0'))

    cargos_fijos = sum((c.valor for c in variante.cargos.all() if not c.opcional), Decimal('0'))

    base = variante.costo_base if costo_base_override is None else costo_base_override
    return finalizar((base + metros_costo + cargos_fijos + cargos_opcionales) * multiplicador)


def opcionales_de_variante(variante, multiplicador_general=None, grupo=None, grupos=None, multiplicador_override=None):
    """Solo importes de venta. Los especiales con material ofrecen valores por grupo.
    Un conjunto ofrece además los opcionales de sus piezas, por la cantidad de cada pieza."""
    multiplicador = (Decimal(str(multiplicador_override)) if multiplicador_override is not None
                     else multiplicador_efectivo(variante, multiplicador_general))
    resultado = []
    for c in variante.cargos.all():
        if not c.opcional:
            continue
        item = {'id': c.id, 'descripcion': c.descripcion, 'especial': c.especial_id is not None, 'preseleccionado': c.preseleccionado,
                'decorativos': c.tipo == CargoVariante.TIPO_DECORATIVOS,
                # Se puede llevar más de una unidad (p. ej. 2 reclinos); cojines y transporte, una.
                'multiple': c.tipo not in (CargoVariante.TIPO_DECORATIVOS, CargoVariante.TIPO_TRANSPORTE)}
        if c.tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE:
            config = configuracion_cargo(c)
            material = bool(config.get('metraje_tela') or config.get('decimetraje_cuero'))
            if grupo is not None and not admite_grupo(config, grupo):
                continue
            if material:
                disponibles = grupos if grupos is not None else obtener_grupos_tela()
                item['precios'] = [{'grupo': g.pk, 'valor': precio_configuracion(config, g, multiplicador_general)}
                                   for g in disponibles if admite_grupo(config, g)]
                item['valor'] = precio_configuracion(config, grupo, multiplicador_general) if grupo is not None else None
            else:
                item['valor'] = precio_configuracion(config, grupo, multiplicador_general)
        else:
            item['valor'] = c.valor if c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO else c.valor * multiplicador
        resultado.append(item)
    for comp in componentes_de(variante):
        for item in opcionales_de_variante(comp.variante, multiplicador_general, grupo, grupos, comp.multiplicador):
            n = comp.cantidad
            item['pieza'] = comp.variante.nombre_catalogo
            item['descripcion'] = f"{item['descripcion']} · {comp.variante.nombre_catalogo}{f' ×{n}' if n > 1 else ''}"
            if item.get('valor') is not None:
                item['valor'] = item['valor'] * n
            for p in item.get('precios', []):
                p['valor'] = p['valor'] * n
            resultado.append(item)
    return resultado


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
        if usa_tela(variante):
            todos_grupos = grupos if grupos is not None else obtener_grupos_tela()
            return [
                {'grupo': g.id, 'grupo_nombre': g.nombre, 'precio': calcular_precio(variante, g, multiplicador_general=multiplicador_general)}
                for g in todos_grupos if grupo_aplicable(variante, g)
            ]
        return [{'grupo': None, 'grupo_nombre': None, 'precio': calcular_precio(variante, None, multiplicador_general=multiplicador_general)}]

    resultado = []
    for fila in filas:
        if fila.grupo is not None and not grupo_aplicable(variante, fila.grupo):
            continue
        resultado.append({
            'grupo': fila.grupo_id,
            'grupo_nombre': fila.grupo.nombre if fila.grupo else None,
            'precio': calcular_precio(variante, fila.grupo, multiplicador_general=multiplicador_general),
        })
    if not resultado and componentes_de(variante) and not usa_tela(variante):
        # Conjunto sin tela con filas de grupos que no aplican: igual tiene su precio único.
        resultado.append({'grupo': None, 'grupo_nombre': None, 'precio': calcular_precio(variante, None, multiplicador_general=multiplicador_general)})
    return resultado


def impacto_categoria(categoria):
    """Vista previa de impacto antes de desactivar/borrar una categoría —
    ya no afecta ningún precio (el precio por grupo es global), solo
    cuántas líneas/variantes quedarían sin esa etiqueta de tipo de mueble."""
    variantes = productos_publicados(categoria.variantes.all())
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
    directas = productos_publicados().filter(multiplicador=multiplicador)
    if multiplicador.es_general:
        heredadas = productos_publicados().filter(multiplicador__isnull=True)
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
    _invalidar_catalogo()
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
        qs = qs.filter(Q(subcategoria__categoria_id=categoria_id) | Q(linea__referencia__isnull=True, categoria_id=categoria_id))
    if linea_id:
        qs = qs.filter(linea_id=linea_id)
    if variante_ids:
        qs = qs.filter(id__in=variante_ids)

    actualizadas = qs.update(multiplicador_id=multiplicador_id)
    _invalidar_catalogo()  # update() no dispara señales
    return actualizadas


def simular_multiplicador(multiplicador, nuevo_valor, limite_ejemplos=20):
    """Simula el impacto de cambiar el valor de un multiplicador antes de guardarlo.
    Devuelve conteo de variantes afectadas y hasta 20 ejemplos antes/después."""
    nuevo_valor = Decimal(str(nuevo_valor))
    directas = list(
        productos_publicados().filter(multiplicador=multiplicador)
        .select_related('linea', 'categoria')
        .prefetch_related('cargos', 'precios')
    )
    if multiplicador.es_general:
        heredadas = list(
            productos_publicados().filter(multiplicador__isnull=True)
            .select_related('linea', 'categoria')
            .prefetch_related('cargos', 'precios')
        )
        variantes_todas = directas + heredadas
    else:
        variantes_todas = directas

    total_afectadas = len(variantes_todas)
    ejemplos = []
    grupos = obtener_grupos_tela()

    for v in variantes_todas[:limite_ejemplos]:
        g = next((g for g in grupos if grupo_aplicable(v, g)), None) if usa_tela(v) else None
        p_actual = calcular_precio(v, g).quantize(Decimal('0.01'))
        p_nuevo = calcular_precio(v, g, multiplicador_override=nuevo_valor).quantize(Decimal('0.01'))
        ejemplos.append({
            'variante_id': v.id,
            'variante_nombre': v.nombre_catalogo,
            'linea_nombre': nombre_linea(v.linea),
            'categoria_nombre': categoria_variante(v).nombre if categoria_variante(v) else '',
            'grupo_nombre': g.nombre if g else 'Sin tela',
            'precio_actual': str(p_actual),
            'precio_nuevo': str(p_nuevo),
            'diferencia': str(p_nuevo - p_actual),
        })

    return {
        'multiplicador_id': multiplicador.id,
        'multiplicador_nombre': multiplicador.nombre,
        'valor_actual': str(multiplicador.valor),
        'valor_nuevo': str(nuevo_valor),
        'variantes_afectadas': total_afectadas,
        'ejemplos': ejemplos,
    }



# --- Juegos y variantes especiales (2026-10-09) ---------------------------------

def preparar_componentes(juego, componentes):
    """Valida y arma piezas sin escribir. Los valores nulos heredan del producto original."""
    if not isinstance(componentes, list) or len(componentes) > 100:
        raise ValidationError({'componentes': 'Envía una lista de hasta 100 piezas.'})
    if componentes and juego.pk and juego.en_juegos.exists():
        raise ValidationError({'componentes': 'Esta variante ya es parte de otro juego; no puede ser un juego.'})
    ids = [item.get('variante') for item in componentes if isinstance(item, dict)]
    if any(isinstance(vid, bool) or not str(vid).isdigit() for vid in ids):
        raise ValidationError({'componentes': 'Selecciona un producto válido para cada pieza.'})
    variantes = {v.pk: v for v in VarianteProducto.objects.filter(pk__in=ids)
                 .select_related('multiplicador', 'linea__referencia').prefetch_related('componentes', 'cargos__especial', 'precios__grupo')}
    anteriores = {c.variante_id: c.adicionales for c in componentes_de(juego)}
    vistos, nuevos = set(), []
    for i, item in enumerate(componentes):
        try:
            vid = int(item.get('variante'))
            raw = item.get('cantidad', 1)
            if isinstance(raw, bool) or not str(raw).isdigit():
                raise ValueError()
            cantidad = int(raw)
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({'componentes': 'Componente inválido.'})
        if cantidad < 1 or cantidad > 99:
            raise ValidationError({'componentes': 'La cantidad de cada componente va de 1 a 99.'})
        v = variantes.get(vid)
        if not v or not misma_coleccion(v, juego):
            raise ValidationError({'componentes': 'Las piezas deben ser productos de la misma referencia (de cualquiera de sus proveedores).'})
        if v.pk == juego.pk or list(v.componentes.all()):
            raise ValidationError({'componentes': f'«{v.nombre_catalogo}» no puede ser componente (es el mismo juego u otro juego).'})
        if v.pk in vistos:
            raise ValidationError({'componentes': f'«{v.nombre_catalogo}» está repetido: ajusta su cantidad.'})
        vistos.add(v.pk)
        valores = {}
        for campo in ('costo_unitario', 'multiplicador'):
            valor = item.get(campo)
            if valor is not None:
                try:
                    valor = Decimal(str(valor))
                    maximo = Decimal('9999999999') if campo == 'costo_unitario' else Decimal('999.999')
                    precision = Decimal('1') if campo == 'costo_unitario' else Decimal('.001')
                    if (not valor.is_finite() or valor < 0 or valor > maximo or valor != valor.quantize(precision)
                            or (campo == 'multiplicador' and valor == 0)):
                        raise ValueError()
                except (ValueError, InvalidOperation):
                    raise ValidationError({'componentes': f'Revisa el {campo.replace("_", " ")} de «{v.nombre_catalogo}». Usa costos en pesos enteros y múltiplos mayores a cero con hasta tres decimales.'})
            valores[campo] = valor
        adicionales = validar_adicionales(item.get('adicionales', anteriores.get(v.pk, [])))
        nuevos.append(ComponenteJuego(juego=juego, variante=v, cantidad=cantidad, orden=i, adicionales=adicionales, **valores))
    return nuevos


def misma_coleccion(pieza, juego):
    """Un conjunto no tiene proveedor propio (2026-10-16): sus piezas son subcategorías de la
    misma referencia comercial y cada una conserva el proveedor de su ficha (p. ej. tapa de un
    proveedor, base de otro y sillas de un tercero). Sin referencia, solo su propia línea."""
    if pieza.linea_id == juego.linea_id:
        return True
    from .disposicion import clave_referencia
    ref_pieza, ref_juego = pieza.linea.referencia, juego.linea.referencia
    return bool(ref_pieza and ref_juego and clave_referencia(ref_pieza.nombre) == clave_referencia(ref_juego.nombre))


def _bloquear_coleccion(linea):
    """Orden de bloqueo común también cuando las piezas vienen de varias listas."""
    if not linea.referencia_id:
        LineaProducto.objects.select_for_update().get(pk=linea.pk)
        return []
    from ordenes.models import Referencia
    from .disposicion import clave_referencia
    clave = clave_referencia(linea.referencia.nombre)
    ids = [pk for pk, nombre in Referencia.objects.values_list('pk', 'nombre') if clave_referencia(nombre) == clave]
    list(LineaProducto.objects.select_for_update().filter(referencia_id__in=ids).order_by('pk'))
    return ids


def _con_componentes(juego, nuevos):
    simulacion = copy(juego)
    simulacion._prefetched_objects_cache = {**getattr(juego, '_prefetched_objects_cache', {}), 'componentes': nuevos}
    return simulacion


def simular_componentes(juego, componentes, grupos=None, multiplicador_general=None):
    nuevos = preparar_componentes(juego, componentes)
    simulacion = _con_componentes(juego, nuevos)
    grupos = grupos if grupos is not None else obtener_grupos_tela()
    por_id = {g.pk: g for g in grupos}
    precios = precios_por_variante(simulacion, grupos, multiplicador_general)
    return {
        'precios_venta': precios,
        'costo_base_componentes': sum(((c.costo_unitario if c.costo_unitario is not None else c.variante.costo_base) * c.cantidad for c in nuevos), Decimal('0')),
        'costo_total_producto': str(costo_lista(simulacion, sin_material=True)),
        'costos_por_grupo': [{'grupo': p['grupo'], 'grupo_nombre': p['grupo_nombre'], 'costo': str(costo_lista(simulacion, por_id.get(p['grupo'])))} for p in precios],
    }


@transaction.atomic
def guardar_componentes(juego, componentes):
    # Todas las conversiones de una colección comparten bloqueo: evita ciclos en peticiones concurrentes.
    _bloquear_coleccion(juego.linea)
    nuevos = preparar_componentes(juego, componentes)
    # Confirmar el cálculo antes de escribir: un error económico no debe dejar datos a medias.
    general = Multiplicador.objects.filter(es_general=True).values_list('valor', flat=True).first()
    precios_por_variante(_con_componentes(juego, nuevos), grupos=obtener_grupos_tela(), multiplicador_general=general)
    if juego.linea.referencia_id:
        juego.costo_confirmado = bool(componentes)
        juego.save(update_fields=['costo_confirmado'])
        if not componentes:
            juego.publicado = False
            juego.save(update_fields=['publicado'])
            LineaProducto.objects.filter(pk=juego.linea_id).update(activo=False)
    juego.componentes.all().delete()
    ComponenteJuego.objects.bulk_create(nuevos)
    from .especiales import archivar_configuracion
    for c in nuevos:
        for adicional in c.adicionales:
            if adicional['tipo'] == 'especial':
                archivar_configuracion(adicional['nombre'], adicional['configuracion'], f'{juego.linea.nombre} · {juego.nombre} · {c.variante.nombre_catalogo}'[:200])
    _invalidar_catalogo()  # bulk_create no dispara señales


@transaction.atomic
def crear_agrupacion(linea, nombre, categoria, componentes, subcategoria=None):
    if not componentes:
        raise ValidationError({'componentes': 'Agrega al menos una pieza para crear una agrupación.'})
    # La referencia que aloja la ficha es un detalle de almacenamiento, no el proveedor
    # del conjunto. Bloquear las referencias homónimas evita creaciones duplicadas.
    ids = _bloquear_coleccion(linea)
    if linea.referencia_id:
        from ordenes.models import Referencia
        from suministros.models import Categoria, Subcategoria
        from .disposicion import disposicion, guardar_disposicion
        list(Referencia.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    if linea.referencia_id:
        if subcategoria:
            juego = linea.variantes.filter(subcategoria=subcategoria).first()
            if not juego:
                raise ValidationError({'subcategoria': 'Actualiza las subcategorías de la referencia antes de formar el conjunto.'})
            guardar_componentes(juego, componentes)
            return juego
        nombre = nombre.strip()
        if not nombre or len(nombre) > 100 or categoria is None:
            raise ValidationError({'nombre': 'Indica la categoría y un nombre de 1 a 100 caracteres.'})
        Categoria.objects.select_for_update().get(pk=categoria.pk)
        if Subcategoria.objects.filter(referencias__pk__in=ids, categoria=categoria, nombre__iexact=nombre).exists():
            raise ValidationError({'nombre': 'Esta referencia ya tiene una subcategoría con ese nombre. Usa otro nombre; no se reemplazarán sus costos.'})
        config = disposicion(linea.referencia.nombre)
        anteriores = list(Subcategoria.objects.filter(referencias__pk__in=ids).distinct().order_by('categoria__nombre', 'nombre', 'pk').values_list('pk', flat=True))
        orden_subs = [pk for pk in config['orden'] if pk in anteriores]
        orden_subs += [pk for pk in anteriores if pk not in orden_subs]
        subcategoria = Subcategoria.objects.filter(categoria=categoria, nombre__iexact=nombre).order_by('pk').first()
        if subcategoria is None:
            subcategoria = Subcategoria.objects.create(categoria=categoria, nombre=nombre)
        linea.referencia.categorias.add(categoria)
        linea.referencia.subcategorias.add(subcategoria)
        guardar_disposicion(linea.referencia, config['revision'], orden=[pk for pk in orden_subs if pk not in config['retiradas']] + [subcategoria.pk])
        clasificacion = {'categoria_referencia': categoria, 'subcategoria': subcategoria}
        # La nueva subcategoría se revisa antes de publicar; cada pieza conserva su proveedor.
        LineaProducto.objects.filter(pk=linea.pk).update(activo=False)
        linea.activo = False
    else:
        clasificacion = {'categoria': categoria}
    ultimo = VarianteProducto.objects.filter(linea=linea).order_by('-orden').first()
    juego = VarianteProducto.objects.create(linea=linea, nombre=nombre, **clasificacion,
                                            costo_base=0, orden=ultimo.orden + 1 if ultimo else 0)
    juego._prefetched_objects_cache = {'cargos': [], 'precios': []}
    guardar_componentes(juego, componentes)
    return juego


class OrdenVariantesDesactualizado(APIException):
    status_code = 409
    default_detail = 'Las variantes cambiaron en otra sesión. Actualizamos la lista; vuelve a arrastrar para guardar el orden.'


@transaction.atomic
def ordenar_variantes(linea, ids, orden_anterior):
    LineaProducto.objects.select_for_update().get(pk=linea.pk)
    variantes = list(VarianteProducto.objects.select_for_update().filter(linea=linea))
    from .disposicion import disposicion, guardar_disposicion
    config = disposicion(linea.referencia.nombre) if linea.referencia_id else {'orden': [], 'retiradas': []}
    posiciones_sub = {pk: i for i, pk in enumerate(config['orden'])}
    visibles = sorted((v for v in variantes if v.subcategoria_id not in config['retiradas']),
                      key=lambda v: (posiciones_sub.get(v.subcategoria_id, len(posiciones_sub)), v.orden, v.pk))
    actuales = [v.pk for v in visibles]
    if len(ids) != len(set(ids)) or set(ids) != set(actuales) or orden_anterior != actuales:
        raise OrdenVariantesDesactualizado()
    todos = ids + [v.pk for v in variantes if v.pk not in ids]
    posiciones = {pk: i for i, pk in enumerate(todos)}
    for v in variantes:
        v.orden = posiciones[v.pk]
    VarianteProducto.objects.bulk_update(variantes, ['orden'])
    if linea.referencia_id:
        por_id = {v.pk: v.subcategoria_id for v in variantes}
        linea._disposicion_resultado = guardar_disposicion(linea.referencia, config['revision'], orden_parcial=[por_id[pk] for pk in ids])

    _invalidar_catalogo()
    return ids


@transaction.atomic
def aplicar_especial(especial, aplicaciones=None, diferencia_precio=False):
    """Sincroniza los cargos opcionales de una variante especial: uno por cada variante de
    la línea a la que aplica. Aplicaciones: [{'variante': id, 'valor': x}]; None = todas
    con el valor por defecto."""
    variantes = {v.pk: v for v in especial.linea.variantes.select_related('multiplicador').prefetch_related(
        'precios__grupo', 'cargos', *PREFETCH_JUEGOS)}
    grupos = None
    general = None
    if aplicaciones is None:
        campo = 'diferencia_precio' if diferencia_precio else 'valor'
        aplicaciones = [{'variante': pk, campo: especial.valor} for pk in variantes]
    if not isinstance(aplicaciones, list) or (diferencia_precio and not aplicaciones):
        raise ValidationError({'aplicaciones': 'Selecciona al menos un producto para el especial.'})
    actuales = {c.variante_id: c for c in especial.cargos.all()}
    usados = set()
    for item in aplicaciones:
        try:
            raw_id = item.get('variante')
            vid = int(raw_id)
            if isinstance(raw_id, bool) or str(vid) != str(raw_id):
                raise ValueError('Variante inválida')
            es_diferencia = 'diferencia_precio' in item or diferencia_precio
            campo = 'diferencia_precio' if es_diferencia else 'valor'
            valor = Decimal(str(item.get(campo, especial.valor)))
            if not valor.is_finite() or abs(valor) >= Decimal('10000000000') or (es_diferencia and valor != valor.to_integral_value()):
                raise ValueError('Importe inválido')
        except (TypeError, ValueError, ArithmeticError, AttributeError):
            raise ValidationError({'aplicaciones': 'Variante o valor inválido.'})
        if vid not in variantes:
            raise ValidationError({'aplicaciones': 'Solo se aplica a variantes de la misma línea.'})
        if vid in usados:
            raise ValidationError({'aplicaciones': 'Un producto no puede estar repetido.'})
        if es_diferencia and valor < 0:
            if grupos is None:
                grupos, general = obtener_grupos_tela(), obtener_multiplicador_general()
            precios = precios_por_variante(variantes[vid], grupos=grupos, multiplicador_general=general)
            if any(p['precio'] + valor < 0 for p in precios):
                raise ValidationError({'aplicaciones': f'La diferencia deja un precio de {variantes[vid].nombre} por debajo de cero.'})
        usados.add(vid)
        cargo = actuales.get(vid)
        tipo = CargoVariante.TIPO_DIFERENCIA_PRECIO if es_diferencia else ''
        if cargo:
            cargo.descripcion, cargo.valor, cargo.opcional, cargo.tipo = especial.nombre, valor, True, tipo
            cargo.save(update_fields=['descripcion', 'valor', 'opcional', 'tipo'])
        else:
            CargoVariante.objects.create(variante=variantes[vid], descripcion=especial.nombre, valor=valor, opcional=True, especial=especial, tipo=tipo)
    especial.cargos.exclude(variante_id__in=usados).delete()
