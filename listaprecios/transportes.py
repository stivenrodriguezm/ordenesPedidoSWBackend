"""«Transporte» por envío (2026-10-21).

El cargo de transporte va en el precio de lista de cada producto (un producto suelto lleva
el suyo), pero se cobra por envío, no por unidad:

- Dentro de un conjunto (tapa + base + sillas) se cobra un solo transporte: el mayor de sus
  piezas. Aplica al precio del conjunto en la lista y a las piezas reunidas en un conjunto
  en cotizaciones y ventas.
- Cada transporte lleva hasta `unidades_por_transporte` unidades del producto (p. ej. 6
  sillas); vacío = todas las unidades de la línea en un solo transporte.
- Productos distintos conservan cada uno su transporte.

Lo que no se cobra se descuenta de la línea («transporte compartido»), igual que los
decorativos incluidos. Una sola regla para la lista, las cotizaciones y las ventas.
"""
from decimal import Decimal
from math import ceil

from .models import CargoVariante


def cargo_transporte(variante):
    """El cargo de transporte del producto (usa los cargos ya precargados)."""
    return next((c for c in variante.cargos.all() if c.tipo == CargoVariante.TIPO_TRANSPORTE), None)


def activo(cargo, opcionales=None):
    """Obligatorio: siempre. Opcional: si se eligió; sin selección (None), si está habilitado."""
    if cargo is None:
        return False
    if not cargo.opcional:
        return True
    return cargo.preseleccionado if opcionales is None else cargo.pk in set(opcionales)


def valor_venta(variante, opcionales=None, multiplicador=None, general=None):
    """Lo que suma un transporte al precio de una unidad (0 si no lleva o no está activo)."""
    cargo = cargo_transporte(variante)
    if not activo(cargo, opcionales):
        return Decimal(0)
    if multiplicador is None:
        from .services import multiplicador_efectivo
        multiplicador = multiplicador_efectivo(variante, general)
    return cargo.valor * Decimal(str(multiplicador))


def valor_costo(variante, opcionales=None):
    cargo = cargo_transporte(variante)
    return cargo.valor if activo(cargo, opcionales) else Decimal(0)


def cupo(variante):
    cargo = cargo_transporte(variante)
    return cargo.unidades_por_transporte if cargo else None


def necesarios(unidades, cupo_transporte):
    """Transportes que necesita una línea de `unidades` del mismo producto."""
    if unidades <= 0:
        return 0
    return ceil(unidades / cupo_transporte) if cupo_transporte else 1


def descuento_conjunto(valores):
    """`valores` = [(valor de un transporte, cantidad)] de las piezas de un conjunto. Se cobra
    uno solo, el mayor; devuelve lo que se descuenta del total que ya los incluía todos."""
    incluidos = sum((v * n for v, n in valores), Decimal(0))
    mayor = max((v for v, n in valores if n > 0), default=Decimal(0))
    return max(incluidos - mayor, Decimal(0))


def calcular_compartidos(items):
    """`items` = [{'clave', 'variante', 'cantidad', 'opcionales'?, 'conjunto'?, 'conjunto_cantidad'?}]
    (variante con cargos precargados, o None). Devuelve {clave: {'transportes', 'valor'}}: cuántos
    transportes se cobran en la línea y cuánto se descuenta por los que viajan juntos.

    Un producto que ya es conjunto en la lista trae un solo transporte por unidad en su precio
    y no se toca aquí. Las piezas reunidas en un conjunto (mismo `conjunto`) cobran uno solo
    por cada conjunto (`conjunto_cantidad`): el de la pieza con el transporte mayor."""
    from .services import componentes_de
    lineas, grupos = [], {}
    for it in items:
        v = it.get('variante')
        if v is None or componentes_de(v):
            continue
        # Una venta guardada pasa su transporte y cupo como se vendió (no los de la lista actual).
        t = Decimal(str(it['valor_transporte'])) if it.get('valor_transporte') is not None else valor_venta(v, it.get('opcionales'))
        if t <= 0:
            continue
        linea = {'clave': it['clave'], 'valor': t, 'cantidad': it['cantidad'], 'cupo': it['cupo'] if 'cupo' in it else cupo(v),
                 'veces': max(1, int(it.get('conjunto_cantidad') or 1))}
        if it.get('conjunto'):
            grupos.setdefault(it['conjunto'], []).append(linea)
        else:
            lineas.append(linea)
    resultado = {}
    for l in lineas:
        cobrados = necesarios(l['cantidad'], l['cupo'])
        if cobrados < l['cantidad']:
            resultado[l['clave']] = {'transportes': cobrados, 'valor': l['valor'] * (l['cantidad'] - cobrados)}
    for piezas in grupos.values():
        mayor = max(piezas, key=lambda p: p['valor'])
        veces = min(mayor['veces'], mayor['cantidad'])
        for p in piezas:
            cobrados = veces if p is mayor else 0
            if cobrados < p['cantidad']:
                resultado[p['clave']] = {'transportes': cobrados, 'valor': p['valor'] * (p['cantidad'] - cobrados)}
    return resultado
