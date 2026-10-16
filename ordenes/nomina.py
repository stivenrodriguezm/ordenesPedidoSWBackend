"""Nómina de asesores (D12a, confirmada por el usuario el 2026-10-06).

Reglas:
- Comisión entre 3 % y 4 % del valor de la venta según el descuento frente al
  precio de lista (tabla editable; cada fila es "hasta X % de descuento → Y %").
  Se paga cuando la venta tiene al menos el 30 % de abono; si no, queda pendiente
  y vuelve a aparecer en los cierres siguientes hasta pagarse.
- Bonificación del 1 % del valor de las ventas del período si el asesor cumple la
  meta. Se causa en ese cierre y se paga desde el cierre siguiente, venta por
  venta, a medida que se entregan.
- Venta compartida: valor / N participantes para comisión, bonificación y meta.
- Salario básico aparte (se paga el día 20); ajustes +/- (adelantos, cuentas por
  cuadrar) por asesor. Todo se edita mientras el cierre está en borrador; una
  línea editada a mano no se recalcula al regenerar.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .estadisticas import participantes
from .models import (
    AsesorCierre, AsesorNomina, CierreNomina, ConfigNomina, CustomUser, LineaNomina, Venta,
)
from .servicios import ErrorNegocio, auditar

CENT = Decimal('0.01')
CIEN = Decimal('100')


def q(valor):
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def config():
    cfg = ConfigNomina.objects.order_by('id').first()
    return cfg or ConfigNomina.objects.create()


def porcentaje_por_descuento(tabla, descuento):
    filas = sorted((Decimal(str(d)), Decimal(str(p))) for d, p in tabla)
    if not filas:
        return Decimal('0')
    for maximo, pct in filas:
        if descuento <= maximo:
            return pct
    return filas[-1][1]


def descuento_pct(valor_venta, precio_lista):
    if not precio_lista or precio_lista <= 0 or precio_lista <= valor_venta:
        return Decimal('0')
    return q((precio_lista - valor_venta) / precio_lista * CIEN)


def abono_pct(venta):
    if not venta.valor_total:
        return Decimal('0')
    return q(Decimal(venta.abono) / Decimal(venta.valor_total) * CIEN)


def base_de(linea):
    return q(linea.valor_venta / (linea.participantes or 1))


def _bloquear_borrador(cierre_id):
    cierre = CierreNomina.objects.select_for_update().get(pk=cierre_id)
    if cierre.estado != 'borrador':
        raise ErrorNegocio('El cierre está cerrado: reábrelo para cambiarlo.', 409)
    return cierre


def _bloquear_fila(fila_id):
    """Fila de asesor abierta, bloqueada para editarla."""
    fila = AsesorCierre.objects.select_for_update().select_related('cierre', 'asesor').get(pk=fila_id)
    if fila.estado == 'cerrado':
        nombre = fila.asesor.first_name or fila.asesor.username
        raise ErrorNegocio(f'La nómina de {nombre} está cerrada: reábrela para cambiarla.', 409)
    return fila


def _sincronizar_estado(cierre):
    """El cierre general queda cerrado solo si todos sus asesores lo están."""
    filas = list(AsesorCierre.objects.filter(cierre=cierre).order_by('-cerrado_en'))
    cerrado = bool(filas) and all(f.estado == 'cerrado' for f in filas)
    cierre.estado = 'cerrado' if cerrado else 'borrador'
    cierre.cerrado_por_id = filas[0].cerrado_por_id if cerrado else None
    cierre.cerrado_en = filas[0].cerrado_en if cerrado else None
    cierre.save(update_fields=['estado', 'cerrado_por', 'cerrado_en'])


def _datos_comision(cierre, venta, n):
    lista = Decimal(venta.valor_lista) if venta.valor_lista else None
    origen = 'manual_historico' if lista else 'sin_precio'
    if venta.revision_productos:
        lineas = list(venta.lineas.all())
        completa = (venta.productos_confirmados and lineas
                    and all(l.precio_lista_unitario is not None for l in lineas)
                    and sum((l.subtotal for l in lineas), Decimal(0)) == venta.valor_total)
        calculada = sum(((l.precio_lista_unitario or 0) * l.cantidad for l in lineas), Decimal(0))
        if not completa or calculada != lista:
            lista, origen = None, 'sin_confirmar'
        else:
            origen = 'productos'
    desc = descuento_pct(Decimal(venta.valor_total), lista) if lista else None
    pct = porcentaje_por_descuento(cierre.tabla_comision, desc) if lista else None
    base = q(Decimal(venta.valor_total) / n)
    return {'precio_lista': lista, 'descuento_pct': desc, 'porcentaje': pct,
            'valor': q(base * (pct or 0) / CIEN), 'origen_precio': origen,
            'revision_productos': venta.revision_productos}


@transaction.atomic
def crear_cierre(usuario, fecha_inicio, fecha_fin, nombre=''):
    if fecha_fin < fecha_inicio:
        raise ErrorNegocio('La fecha final debe ser posterior a la inicial.', 400, 'fecha_fin')
    cfg = config()
    if cfg.ventas_desde is None:
        # Primer cierre: las ventas anteriores se liquidaron fuera del sistema.
        cfg.ventas_desde = fecha_inicio
        cfg.save(update_fields=['ventas_desde'])
    cierre = CierreNomina.objects.create(
        nombre=nombre or f'Nómina {fecha_inicio:%d/%m/%Y} – {fecha_fin:%d/%m/%Y}',
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, tabla_comision=cfg.tabla_comision,
        abono_minimo_pct=cfg.abono_minimo_pct, bonificacion_pct=cfg.bonificacion_pct, creado_por=usuario)
    auditar(usuario, 'nomina.cierre_creado', cierre, {'desde': fecha_inicio, 'hasta': fecha_fin})
    _generar(cierre)
    return cierre


@transaction.atomic
def actualizar_fijos(asesor_id):
    """Tras cambiar básico o meta en la configuración: recalcula los cierres donde ese
    asesor sigue con la nómina abierta (los cerrados quedan como se pagaron)."""
    ids = AsesorCierre.objects.filter(asesor_id=asesor_id, estado='abierto').values_list('cierre_id', flat=True)
    for cierre in CierreNomina.objects.select_for_update().filter(pk__in=list(ids), estado='borrador'):
        _generar(cierre)


@transaction.atomic
def regenerar(cierre_id, usuario):
    cierre = _bloquear_borrador(cierre_id)
    _generar(cierre)
    auditar(usuario, 'nomina.cierre_regenerado', cierre)
    return cierre


def _generar(cierre):
    cfg = config()
    # Las ventas del propio rango siempre entran, aunque el cierre sea anterior al primero
    # creado; las pendientes de antes solo llegan desde `ventas_desde`.
    desde = min(cfg.ventas_desde or cierre.fecha_inicio, cierre.fecha_inicio)
    ventas = list(Venta.objects.filter(fecha_venta__gte=desde, fecha_venta__lte=cierre.fecha_fin)
                  .exclude(estado=Venta.ESTADO_ANULADA).select_related('cliente').prefetch_related('vendedores_compartidos', 'lineas')
                  .order_by('fecha_venta', 'id'))
    # Lo pagado cuenta por asesor: las líneas de nóminas de asesor ya cerradas en otros cierres.
    pagadas = set(LineaNomina.objects.filter(asesor_cierre__estado='cerrado', pagar=True).exclude(asesor_cierre__cierre=cierre)
                  .exclude(tipo='ajuste').values_list('tipo', 'venta_id', 'asesor_cierre__asesor_id'))

    # Asesores del cierre: quienes vendieron y quienes tienen datos de nómina activos.
    ids = {a for v in ventas for a in participantes(v)}
    ids |= set(AsesorNomina.objects.filter(activo=True).values_list('asesor_id', flat=True))
    ids |= set(cierre.asesores.values_list('asesor_id', flat=True))
    fijos = {a.asesor_id: a for a in AsesorNomina.objects.filter(asesor_id__in=ids)}
    ventas_periodo = defaultdict(Decimal)
    for v in ventas:
        if v.fecha_venta >= cierre.fecha_inicio:
            n = len(participantes(v))
            for a in participantes(v):
                ventas_periodo[a] += q(Decimal(v.valor_total) / n)
    # Pocas consultas: con la base remota cada ida y vuelta cuesta (P08).
    filas = {f.asesor_id: f for f in AsesorCierre.objects.filter(cierre=cierre)}
    faltan = set(CustomUser.objects.filter(id__in=ids).values_list('id', flat=True)) - set(filas)
    AsesorCierre.objects.bulk_create([AsesorCierre(
        cierre=cierre, asesor_id=a,
        salario_basico=fijos[a].salario_basico if a in fijos else Decimal('0'),
        meta=fijos[a].meta if a in fijos else Decimal('0')) for a in faltan])
    # Solo se recalculan los asesores con la nómina abierta; los cerrados quedan congelados.
    filas = {f.asesor_id: f for f in AsesorCierre.objects.filter(cierre=cierre, estado='abierto')}
    for a, fila in filas.items():
        fila.ventas_periodo = ventas_periodo.get(a, Decimal('0'))
        # Básico y meta actuales de la configuración, salvo que se hayan fijado a mano aquí.
        if a in fijos and not fila.basico_manual:
            fila.salario_basico = fijos[a].salario_basico
        if a in fijos and not fila.meta_manual:
            fila.meta = fijos[a].meta
    AsesorCierre.objects.bulk_update(list(filas.values()), ['ventas_periodo', 'salario_basico', 'meta'])

    LineaNomina.objects.filter(asesor_cierre__cierre=cierre, asesor_cierre__estado='abierto', editada=False).exclude(tipo='ajuste').delete()
    editadas = set(LineaNomina.objects.filter(asesor_cierre__cierre=cierre, editada=True)
                   .values_list('tipo', 'venta_id', 'asesor_cierre__asesor_id'))
    nuevas = []
    for v in ventas:
        socios = participantes(v)
        n = len(socios)
        abono = abono_pct(v)
        comun = {'venta': v, 'valor_venta': Decimal(v.valor_total), 'participantes': n, 'abono_pct': abono,
                 'estado_venta': v.estado, 'descripcion': v.cliente.nombre if v.cliente_id else ''}
        for a in socios:
            if a not in filas:
                continue
            if ('comision', v.id, a) not in pagadas and ('comision', v.id, a) not in editadas:
                datos = _datos_comision(cierre, v, n)
                paga = datos['precio_lista'] is not None and abono >= cierre.abono_minimo_pct
                motivo = ('Completar y confirmar productos / precio de lista' if datos['precio_lista'] is None
                          else ('' if paga else f'Abono menor al {cierre.abono_minimo_pct:g} %'))
                nuevas.append(LineaNomina(asesor_cierre=filas[a], tipo='comision', pagar=paga,
                                          motivo_pendiente=motivo, **comun, **datos))
            # Bonificación ganada en este cierre: se paga desde el siguiente, al entregar.
            if (v.fecha_venta >= cierre.fecha_inicio and filas[a].cumple_meta
                    and ('bonificacion', v.id, a) not in editadas):
                nuevas.append(LineaNomina(asesor_cierre=filas[a], tipo='bonificacion', causada_en=cierre, pagar=False,
                                          motivo_pendiente='Se paga desde el próximo cierre, al entregar',
                                          porcentaje=cierre.bonificacion_pct,
                                          valor=q(Decimal(v.valor_total) / n * cierre.bonificacion_pct / CIEN), **comun))

    # Bonificaciones ganadas en cierres anteriores (la línea original, en su propio
    # cierre) y aún sin pagar.
    causadas = (LineaNomina.objects.filter(tipo='bonificacion', asesor_cierre__estado='cerrado',
                                           asesor_cierre__cierre=F('causada_en')).exclude(causada_en=cierre)
                .select_related('venta__cliente', 'asesor_cierre', 'causada_en'))
    for b in causadas:
        a = b.asesor_cierre.asesor_id
        clave = ('bonificacion', b.venta_id, a)
        if clave in pagadas or clave in editadas or a not in filas or b.venta.estado == Venta.ESTADO_ANULADA:
            continue
        entregada = b.venta.estado == 'entregado'
        nuevas.append(LineaNomina(
            asesor_cierre=filas[a], tipo='bonificacion', causada_en=b.causada_en, venta=b.venta, pagar=entregada,
            motivo_pendiente='' if entregada else 'Pendiente de entrega',
            descripcion=b.descripcion, valor_venta=b.valor_venta, participantes=b.participantes, porcentaje=b.porcentaje,
            valor=b.valor, abono_pct=abono_pct(b.venta), estado_venta=b.venta.estado))
    LineaNomina.objects.bulk_create(nuevas)


def descuento_global(ventas, lista):
    return q((1 - Decimal(ventas) / Decimal(lista)) * CIEN) if lista else None


def totales(fila):
    lineas = list(fila.lineas.all())
    comisiones = sum((l.valor for l in lineas if l.tipo == 'comision' and l.pagar), Decimal('0'))
    bonificaciones = sum((l.valor for l in lineas if l.tipo == 'bonificacion' and l.pagar), Decimal('0'))
    ajustes = sum((l.valor for l in lineas if l.tipo == 'ajuste'), Decimal('0'))
    # Descuento global: ventas frente a la suma de sus precios de lista (solo ventas con
    # precio de lista; las compartidas, en la parte de este asesor).
    con_lista = [l for l in lineas if l.tipo == 'comision' and l.precio_lista]
    ventas_con_lista = sum((l.valor_venta / (l.participantes or 1) for l in con_lista), Decimal('0'))
    lista_total = sum((l.precio_lista / (l.participantes or 1) for l in con_lista), Decimal('0'))
    return {
        'ventas_con_lista': q(ventas_con_lista), 'lista_total': q(lista_total),
        'descuento_global_pct': descuento_global(ventas_con_lista, lista_total),
        'comisiones': q(comisiones), 'bonificaciones': q(bonificaciones), 'ajustes': q(ajustes),
        'total_nomina': q(comisiones + bonificaciones + ajustes),
        'comisiones_pendientes': q(sum((l.valor for l in lineas if l.tipo == 'comision' and not l.pagar), Decimal('0'))),
        'bonificaciones_pendientes': q(sum((l.valor for l in lineas if l.tipo == 'bonificacion' and not l.pagar), Decimal('0'))),
        'salario_basico': q(fila.salario_basico),
    }


@transaction.atomic
def editar_asesor(fila_id, usuario, datos):
    fila = _bloquear_fila(fila_id)
    antes = {'salario_basico': fila.salario_basico, 'meta': fila.meta, 'cumple_meta_manual': fila.cumple_meta_manual}
    for campo in ('salario_basico', 'meta'):
        if campo in datos:
            setattr(fila, campo, q(Decimal(str(datos[campo] or 0))))
    fila.basico_manual = fila.basico_manual or 'salario_basico' in datos
    fila.meta_manual = fila.meta_manual or 'meta' in datos
    if 'cumple_meta_manual' in datos:
        fila.cumple_meta_manual = datos['cumple_meta_manual']
    if 'nota' in datos:
        fila.nota = str(datos['nota'] or '')[:2000]
    fila.save()
    auditar(usuario, 'nomina.asesor_editado', fila, {'antes': antes, 'despues': datos})
    # La meta cambia qué bonificaciones se causan: se recalculan las líneas automáticas.
    _generar(fila.cierre)
    return fila


@transaction.atomic
def editar_linea(linea_id, usuario, datos):
    linea = LineaNomina.objects.select_related('asesor_cierre__cierre', 'venta').get(pk=linea_id)
    cierre = _bloquear_fila(linea.asesor_cierre_id).cierre
    if linea.tipo == 'comision' and linea.venta_id and linea.venta.revision_productos and 'precio_lista' in datos:
        if datos.get('guardar_en_venta', True):
            raise ErrorNegocio('Corrige el precio en los productos de la venta. Para una excepción solo en nómina usa guardar_en_venta=false y una nota.', 400)
        if not str(datos.get('nota', '')).strip():
            raise ErrorNegocio('La excepción de nómina requiere una nota.', 400)
    if linea.tipo == 'comision' and not linea.precio_lista and datos.get('pagar'):
        if not datos.get('precio_lista') and not (str(datos.get('nota', '')).strip() and ('valor' in datos or 'porcentaje' in datos)):
            raise ErrorNegocio('Falta confirmar el precio de lista o justificar un importe manual.', 400)
    antes = {'precio_lista': linea.precio_lista, 'porcentaje': linea.porcentaje, 'valor': linea.valor, 'pagar': linea.pagar}
    if 'precio_lista' in datos and linea.tipo == 'comision':
        lista = Decimal(str(datos['precio_lista'])) if datos['precio_lista'] not in (None, '') else None
        if lista is not None and (not lista.is_finite() or lista <= 0):
            raise ErrorNegocio('El precio de lista debe ser positivo.', 400)
        linea.precio_lista = lista
        linea.origen_precio = 'ajuste_manual'
        linea.descuento_pct = descuento_pct(linea.valor_venta, lista)
        if 'porcentaje' not in datos:
            linea.porcentaje = porcentaje_por_descuento(cierre.tabla_comision, linea.descuento_pct)
        if datos.get('guardar_en_venta', True) and linea.venta_id:
            Venta.objects.filter(pk=linea.venta_id).update(valor_lista=lista)
    if 'porcentaje' in datos and datos['porcentaje'] not in (None, ''):
        linea.porcentaje = Decimal(str(datos['porcentaje']))
    if 'valor' in datos and datos['valor'] not in (None, ''):
        linea.valor = q(Decimal(str(datos['valor'])))
    elif linea.tipo != 'ajuste' and ('precio_lista' in datos or 'porcentaje' in datos):
        linea.valor = q(base_de(linea) * (linea.porcentaje or 0) / CIEN)
    if 'pagar' in datos:
        linea.pagar = bool(datos['pagar'])
        linea.motivo_pendiente = '' if linea.pagar else (linea.motivo_pendiente or 'Pendiente por decisión manual')
    for campo in ('nota', 'descripcion'):
        if campo in datos:
            setattr(linea, campo, str(datos[campo] or '')[:255 if campo == 'descripcion' else 2000])
    if linea.tipo == 'comision' and linea.precio_lista is None and not ('valor' in datos or 'porcentaje' in datos):
        linea.pagar = False
        linea.porcentaje = None
        linea.descuento_pct = None
        linea.valor = Decimal(0)
        linea.motivo_pendiente = 'Completar y confirmar productos / precio de lista'
    linea.editada = True
    linea.save()
    auditar(usuario, 'nomina.linea_editada', linea, {'antes': antes, 'despues': datos})
    return linea


@transaction.atomic
def agregar_ajuste(fila_id, usuario, descripcion, valor):
    fila = _bloquear_fila(fila_id)
    descripcion = str(descripcion or '').strip()
    if not descripcion:
        raise ErrorNegocio('Describe el ajuste (p. ej. "Adelanto del 15").', 400, 'descripcion')
    try:
        valor = q(Decimal(str(valor)))
    except Exception:
        raise ErrorNegocio('Valor inválido.', 400, 'valor')
    if valor == 0:
        raise ErrorNegocio('El valor no puede ser cero: usa negativo para descontar.', 400, 'valor')
    linea = LineaNomina.objects.create(asesor_cierre=fila, tipo='ajuste', descripcion=descripcion[:255], valor=valor,
                                       pagar=True, editada=True)
    auditar(usuario, 'nomina.ajuste', linea, {'valor': valor, 'descripcion': descripcion})
    return linea


@transaction.atomic
def borrar_ajuste(linea_id, usuario):
    linea = LineaNomina.objects.select_related('asesor_cierre').get(pk=linea_id)
    _bloquear_fila(linea.asesor_cierre_id)
    if linea.tipo != 'ajuste':
        raise ErrorNegocio('Solo se borran ajustes; una comisión o bonificación se deja sin pagar.', 400)
    auditar(usuario, 'nomina.ajuste_borrado', linea, {'valor': linea.valor, 'descripcion': linea.descripcion})
    linea.delete()


def _cerrar_fila(fila, usuario):
    cierre = fila.cierre
    for linea in (LineaNomina.objects.filter(asesor_cierre=fila, tipo='comision', editada=False)
                  .select_related('venta').prefetch_related('venta__lineas')):
        datos = _datos_comision(cierre, linea.venta, linea.participantes)
        if any(getattr(linea, k) != datos[k] for k in ('revision_productos', 'precio_lista', 'valor')):
            raise ErrorNegocio('Los productos o precios cambiaron. Recalcula la nómina antes de cerrar.', 409)
    fila.estado = 'cerrado'
    fila.cerrado_por = usuario
    fila.cerrado_en = timezone.now()
    fila.save(update_fields=['estado', 'cerrado_por', 'cerrado_en'])
    cfg = config()
    if cfg.ventas_desde and cierre.fecha_inicio < cfg.ventas_desde:
        # Un período anterior quedó liquidado en el sistema: lo que quedó pendiente pasa a
        # los cierres siguientes (al recalcularlos). Mientras estaba abierto no se veía
        # en ellos, así que no hay doble pago.
        cfg.ventas_desde = cierre.fecha_inicio
        cfg.save(update_fields=['ventas_desde'])
    auditar(usuario, 'nomina.asesor_cerrado', fila, {'cierre': cierre.pk, 'asesor': fila.asesor_id})


def _reabrir_fila(fila, usuario):
    posterior = (AsesorCierre.objects.filter(asesor_id=fila.asesor_id, estado='cerrado', cierre__fecha_inicio__gt=fila.cierre.fecha_inicio)
                 .select_related('cierre').first())
    if posterior:
        raise ErrorNegocio(f'Este asesor tiene cerrada una nómina posterior ({posterior.cierre.nombre}): reábrela primero.', 409)
    fila.estado = 'abierto'
    fila.cerrado_por = None
    fila.cerrado_en = None
    fila.save(update_fields=['estado', 'cerrado_por', 'cerrado_en'])
    auditar(usuario, 'nomina.asesor_reabierto', fila, {'cierre': fila.cierre_id, 'asesor': fila.asesor_id})


@transaction.atomic
def cerrar_asesor(fila_id, usuario):
    """Cierra (da por pagada) la nómina de un asesor dentro del cierre."""
    fila = _bloquear_fila(fila_id)
    _cerrar_fila(fila, usuario)
    _sincronizar_estado(fila.cierre)
    return fila


@transaction.atomic
def reabrir_asesor(fila_id, usuario):
    fila = AsesorCierre.objects.select_for_update().select_related('cierre').get(pk=fila_id)
    if fila.estado != 'cerrado':
        raise ErrorNegocio('La nómina de este asesor ya está abierta.', 409)
    _reabrir_fila(fila, usuario)
    _sincronizar_estado(fila.cierre)
    return fila


@transaction.atomic
def cerrar(cierre_id, usuario):
    """Cierra la nómina de todos los asesores que sigan abiertos."""
    cierre = CierreNomina.objects.select_for_update().get(pk=cierre_id)
    for fila in AsesorCierre.objects.select_for_update().filter(cierre=cierre, estado='abierto').select_related('cierre'):
        _cerrar_fila(fila, usuario)
    _sincronizar_estado(cierre)
    auditar(usuario, 'nomina.cierre_cerrado', cierre)
    return cierre


@transaction.atomic
def reabrir(cierre_id, usuario, motivo=None):
    """Reabre la nómina de todos los asesores del cierre (sin pedir justificación)."""
    cierre = CierreNomina.objects.select_for_update().get(pk=cierre_id)
    filas = list(AsesorCierre.objects.select_for_update().filter(cierre=cierre, estado='cerrado').select_related('cierre'))
    if not filas:
        raise ErrorNegocio('El cierre ya está abierto.', 409)
    for fila in filas:
        _reabrir_fila(fila, usuario)
    _sincronizar_estado(cierre)
    auditar(usuario, 'nomina.cierre_reabierto', cierre, {'motivo': str(motivo or '')[:500]})
    return cierre


@transaction.atomic
def borrar_cierre(cierre_id, usuario):
    cierre = CierreNomina.objects.select_for_update().get(pk=cierre_id)
    if AsesorCierre.objects.filter(cierre=cierre, estado='cerrado').exists():
        raise ErrorNegocio('Hay asesores con la nómina cerrada en este cierre: reábrelos antes de borrarlo.', 409)
    auditar(usuario, 'nomina.cierre_borrado', cierre, {'nombre': cierre.nombre})
    LineaNomina.objects.filter(asesor_cierre__cierre=cierre).delete()
    cierre.delete()
