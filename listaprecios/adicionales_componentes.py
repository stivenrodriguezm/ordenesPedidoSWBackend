"""Costos y especiales de una pieza dentro de un conjunto; nunca edita el producto original."""
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from .especiales import admite_grupo, costo_configuracion, precio_configuracion, validar_configuracion


def validar_adicionales(datos):
    if not isinstance(datos, list) or len(datos) > 50:
        raise ValidationError({'adicionales': 'Envía hasta 50 cargos o especiales por pieza.'})
    resultado = []
    for item in datos:
        if isinstance(item, dict) and item.get('tipo') == 'cargo':
            # (2026-10-15) Los cargos de una pieza son los del producto original: se editan allí.
            raise ValidationError({'adicionales': 'Los cargos de una pieza se agregan al producto original, no solo al conjunto.'})
        if not isinstance(item, dict) or item.get('tipo') != 'especial':
            raise ValidationError({'adicionales': 'Elige un especial válido.'})
        nombre = item.get('nombre')
        if not isinstance(nombre, str) or not nombre.strip() or len(nombre.strip()) > 120:
            raise ValidationError({'adicionales': 'Cada cargo o especial debe tener un nombre de hasta 120 caracteres.'})
        nuevo = {'tipo': item['tipo'], 'nombre': nombre.strip()}
        permitidos = {'tipo', 'nombre', 'costo'} if item['tipo'] == 'cargo' else {'tipo', 'nombre', 'configuracion'}
        if set(item) - permitidos:
            raise ValidationError({'adicionales': 'Hay campos no reconocidos en un cargo o especial.'})
        if item['tipo'] == 'cargo':
            try:
                valor = item.get('costo')
                if isinstance(valor, bool) or valor in (None, ''):
                    raise ValueError()
                costo = Decimal(str(valor))
                if not costo.is_finite() or abs(costo) > 9999999999 or costo != costo.to_integral_value():
                    raise ValueError()
            except (ValueError, InvalidOperation):
                raise ValidationError({'adicionales': f'Indica el costo de «{nombre}» en pesos enteros, sin centavos.'})
            nuevo['costo'] = format(costo, 'f')
        else:
            nuevo['configuracion'] = validar_configuracion(item.get('configuracion'))
        resultado.append(nuevo)
    return resultado


def especiales_de(componente):
    return [a['configuracion'] for a in componente.adicionales if a['tipo'] == 'especial']


def tiene_material(componente):
    return any(c.get('metraje_tela') or c.get('decimetraje_cuero') for c in especiales_de(componente))


def admite_material(componente, grupo):
    return all(admite_grupo(c, grupo) for c in especiales_de(componente))


def costo_especial(config, grupo=None, sin_material=False):
    if sin_material:
        config = {**config, 'metraje_tela': None, 'decimetraje_cuero': None}
    return costo_configuracion(config, grupo)


def costo_adicionales(componente, grupo=None, sin_material=False):
    return sum((Decimal(a['costo']) if a['tipo'] == 'cargo' else costo_especial(a['configuracion'], grupo, sin_material)
                for a in componente.adicionales), Decimal('0'))


def venta_adicionales(componente, grupo, multiplicador, general):
    return sum((Decimal(a['costo']) * multiplicador if a['tipo'] == 'cargo'
                else precio_configuracion(a['configuracion'], grupo, general)
                for a in componente.adicionales), Decimal('0'))
