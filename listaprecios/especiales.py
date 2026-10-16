"""Especiales: costo y margen independientes, consumos por material y biblioteca reutilizable."""
import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import CargoVariante, EspecialCatalogo

CAMPOS = {'costo_base', 'multiplicador', 'sentido', 'metraje_tela', 'decimetraje_cuero'}


def numero(valor):
    return format(Decimal(str(valor)).normalize(), 'f')


def validar_configuracion(datos, parcial=False, exigir_enteros=True):
    if not isinstance(datos, dict) or set(datos) - CAMPOS:
        raise ValidationError({'configuracion': 'La configuración del especial no es válida.'})
    resultado = {} if parcial else dict(costo_base='0', multiplicador=None, sentido='sube', metraje_tela=None, decimetraje_cuero=None)
    if not parcial and 'costo_base' not in datos:
        raise ValidationError({'costo_base': 'Indica el costo del especial.'})
    for campo, raw in datos.items():
        if campo == 'sentido':
            if raw not in ('sube', 'baja'):
                raise ValidationError({campo: 'Elige si sube o baja el precio.'})
            resultado[campo] = raw
            continue
        if raw is None and campo != 'costo_base':
            resultado[campo] = None
            continue
        try:
            if isinstance(raw, bool) or raw in (None, ''):
                raise ValueError()
            valor = Decimal(str(raw))
            decimales = 0 if campo == 'costo_base' and exigir_enteros else 3 if campo == 'multiplicador' else 2
            limite = Decimal('10000000000') if campo == 'costo_base' else Decimal('1000') if campo == 'multiplicador' else Decimal('1000000')
            if not valor.is_finite() or valor < 0 or valor >= limite or (campo != 'costo_base' and valor == 0) or valor != valor.quantize(Decimal(10) ** -decimales):
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation):
            mensaje = 'Usa pesos enteros, sin centavos, mayores o iguales a cero.' if campo == 'costo_base' else 'Indica un consumo mayor a cero (máximo 2 decimales).' if campo != 'multiplicador' else 'Indica un multiplicador mayor a cero, menor a 1.000 y con máximo 3 decimales.'
            raise ValidationError({campo: mensaje})
        resultado[campo] = numero(valor)
    return resultado


def configuracion_base(especial, general=None):
    if especial.configuracion:
        return especial.configuracion
    from .services import obtener_multiplicador_general
    cargos = list(especial.cargos.all())
    directo = bool(cargos) and all(c.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO for c in cargos)
    return dict(costo_base=numero(abs(especial.valor)), sentido='baja' if especial.valor < 0 else 'sube',
                multiplicador='1' if directo else numero(general if general is not None else obtener_multiplicador_general()),
                metraje_tela=None, decimetraje_cuero=None)


def configuracion_cargo(cargo, general=None):
    if cargo.tipo == CargoVariante.TIPO_ESPECIAL_CONFIGURABLE:
        return {**cargo.especial.configuracion, **cargo.configuracion_especial}
    from .services import multiplicador_efectivo
    return dict(costo_base=numero(abs(cargo.valor)), sentido='baja' if cargo.valor < 0 else 'sube',
                multiplicador='1' if cargo.tipo == CargoVariante.TIPO_DIFERENCIA_PRECIO else numero(multiplicador_efectivo(cargo.variante, general)),
                metraje_tela=None, decimetraje_cuero=None)


def admite_grupo(config, grupo):
    if not (config.get('metraje_tela') or config.get('decimetraje_cuero')):
        return True
    campo = 'decimetraje_cuero' if grupo is not None and grupo.tipo == 'cuero' else 'metraje_tela'
    return grupo is not None and config.get(campo) is not None


def costo_configuracion(config, grupo=None):
    if not admite_grupo(config, grupo):
        raise ValidationError({'opcionales': 'El especial no tiene consumo para el material elegido. Cambia de grupo o desactiva la opción.'})
    costo = Decimal(config['costo_base'])
    if grupo is not None:
        campo = 'decimetraje_cuero' if grupo.tipo == 'cuero' else 'metraje_tela'
        costo += Decimal(config.get(campo) or '0') * grupo.precio_por_metro
    return costo * (-1 if config.get('sentido') == 'baja' else 1)


def precio_configuracion(config, grupo=None, general=None):
    from .services import obtener_multiplicador_general
    multiplo = config.get('multiplicador')
    if multiplo is None:
        multiplo = general if general is not None else obtener_multiplicador_general()
    return costo_configuracion(config, grupo) * Decimal(str(multiplo))


def archivar_configuracion(nombre, config, origen):
    # Un nombre/costo/margen/consumos idénticos se guardan una sola vez, aunque se usen en muchas líneas.
    canonica = {k: (numero(v) if k not in ('sentido',) and v is not None else v) for k, v in config.items()}
    huella = hashlib.sha256((nombre.strip().casefold() + json.dumps(canonica, sort_keys=True)).encode()).hexdigest()
    return EspecialCatalogo.objects.get_or_create(huella=huella, defaults={'nombre': nombre.strip(), 'configuracion': canonica, 'origen': origen})[0]


@transaction.atomic
def aplicar_configurado(especial, aplicaciones=None):
    from .services import obtener_grupos_tela, obtener_multiplicador_general, precios_por_variante, PREFETCH_JUEGOS
    variantes = {v.pk: v for v in especial.linea.variantes.select_related('multiplicador').prefetch_related('precios__grupo', 'cargos__especial', *PREFETCH_JUEGOS)}
    actuales = {c.variante_id: c for c in especial.cargos.all()}
    if aplicaciones is None:
        aplicaciones = ([{'variante': c.variante_id, 'configuracion': c.configuracion_especial} for c in actuales.values()]
                        if actuales else [{'variante': vid} for vid in variantes])
    if not isinstance(aplicaciones, list) or not aplicaciones:
        raise ValidationError({'aplicaciones': 'Selecciona al menos un producto.'})
    usados = set()
    grupos, general = None, None
    for app in aplicaciones:
        try:
            raw_id = app.get('variante')
            vid = int(raw_id)
            if isinstance(raw_id, bool) or str(raw_id) != str(vid) or vid not in variantes or vid in usados:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({'aplicaciones': 'Selecciona productos de esta colección, sin repetirlos.'})
        if set(app) - {'variante', 'configuracion'}:
            raise ValidationError({'aplicaciones': 'Usa costo, multiplicador y consumos en la configuración del producto.'})
        excepcion = validar_configuracion(app.get('configuracion', {}), parcial=True)
        config = {**especial.configuracion, **excepcion}
        if config['sentido'] == 'baja':
            if grupos is None:
                grupos, general = obtener_grupos_tela(), obtener_multiplicador_general()
            filas = precios_por_variante(variantes[vid], grupos=grupos, multiplicador_general=general)
            por_id = {g.pk: g for g in grupos}
            for fila in filas:
                grupo = por_id.get(fila['grupo'])
                if admite_grupo(config, grupo) and fila['precio'] + precio_configuracion(config, grupo, general) < 0:
                    raise ValidationError({'aplicaciones': f'El especial deja un precio de {variantes[vid].nombre} por debajo de cero.'})
        usados.add(vid)
        cargo = actuales.get(vid)
        valores = dict(descripcion=especial.nombre, valor=Decimal(config['costo_base']), opcional=True,
                       tipo=CargoVariante.TIPO_ESPECIAL_CONFIGURABLE, configuracion_especial=excepcion)
        if cargo:
            for campo, valor in valores.items():
                setattr(cargo, campo, valor)
            cargo.save(update_fields=list(valores))
        else:
            CargoVariante.objects.create(especial=especial, variante=variantes[vid], **valores)
        archivar_configuracion(especial.nombre, config, f'{especial.linea.nombre} · {variantes[vid].nombre}')
    especial.cargos.exclude(variante_id__in=usados).delete()
    archivar_configuracion(especial.nombre, especial.configuracion, especial.linea.nombre)


def archivar_historico(especial, general=None):
    """También los clientes del contrato anterior alimentan la biblioteca, sin convertir sus precios."""
    archivar_configuracion(especial.nombre, configuracion_base(especial, general), especial.linea.nombre)
    for cargo in especial.cargos.all():
        archivar_configuracion(especial.nombre, configuracion_cargo(cargo, general), f'{especial.linea.nombre} · {cargo.variante.nombre}')
