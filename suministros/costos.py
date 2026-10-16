"""Costo integral de un ítem de inventario (P05-02, H24; regla provisional D03).

costo = costo_especifico
      + Σ costos adicionales
      + Σ telas/cueros (costo_unidad × cantidad)          ← modelo nuevo
      + tela heredada (tela_costo_metro × tela_cantidad_metros), SOLO si el
        ítem no tiene filas de telas/cueros (las filas nuevas se crearon
        copiando la tela heredada; sumar ambas la contaría dos veces).

Decimal con 2 decimales y ROUND_HALF_UP. Las cantidades de tela son por unidad
de inventario (cada unidad de un grupo es un ítem propio).
"""
from decimal import Decimal, ROUND_HALF_UP

CENTAVO = Decimal('0.01')


def _d(valor):
    return Decimal(str(valor or 0))


def costo_telas(item):
    filas = list(item.telas_cueros.all())
    if filas:
        return sum((_d(f.costo_unidad) * _d(f.cantidad) for f in filas), Decimal('0'))
    if item.lleva_tela:
        return _d(item.tela_costo_metro) * _d(item.tela_cantidad_metros)
    return Decimal('0')


def costo_integral(item):
    adicionales = sum((_d(c.valor) for c in item.costos_adicionales.all()), Decimal('0'))
    total = _d(item.costo_especifico) + adicionales + costo_telas(item)
    return total.quantize(CENTAVO, rounding=ROUND_HALF_UP)
