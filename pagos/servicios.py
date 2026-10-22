"""Preparar, revisar y exportar pagos con bloqueo, revisión e historial."""
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from django.db import transaction
from django.db.models import F, Max, Q, prefetch_related_objects
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ordenes.models import ComprobanteEgreso, Proveedor, ProveedorTela, CustomUser
from ordenes.servicios import ErrorNegocio, auditar, siguiente_consecutivo
from .beneficiarios import pertenece, huella_ce
from .catalogo import BANCOS, DOCUMENTOS, TIPOS
from .exportadores import nombre_bancario, exportar
from .models import ArchivoLotePago, CuentaBancaria, EmpleadoPago, LotePago, DetallePago, ProgramacionNomina

MAX_CE = Decimal('99999999')


def pesos(valor, cero=False):
    try:
        numero = Decimal(str(valor))
    except (ValueError, TypeError, InvalidOperation):
        raise ErrorNegocio('Introduce un valor en pesos sin separadores ni decimales.', campo='valor')
    if not numero.is_finite() or numero != numero.to_integral_value() or numero < (0 if cero else 1) or numero > MAX_CE:
        raise ErrorNegocio('El pago debe ser un valor entero entre ' + ('0' if cero else '1') + ' y 99.999.999 pesos.', campo='valor')
    return numero


def fecha(valor):
    try:
        return date.fromisoformat(str(valor))
    except (ValueError, TypeError):
        raise ErrorNegocio('Selecciona una fecha válida.', campo='fecha_pago')


def booleano(valor):
    if not isinstance(valor, bool):
        raise ErrorNegocio('El valor debe ser verdadero o falso.')
    return valor


def entero(valor):
    if isinstance(valor, bool) or not re.fullmatch(r'[0-9]+', str(valor or '')):
        raise ErrorNegocio('Identificador inválido.')
    return int(valor)


def revisar_revision(obj, datos):
    if type(datos.get('revision')) is not int or datos.get('revision') != obj.revision:
        raise ErrorNegocio('Otra persona modificó este registro. Recarga para revisar sus cambios.', 409)


def snapshot(c):
    return {k: getattr(c, k) for k in ('id', 'banco', 'tipo', 'numero', 'tipo_documento', 'documento', 'nombres', 'apellidos', 'alias')}


def huella_lote(lote, pagos):
    datos = {'id': lote.id, 'revision': lote.revision, 'fecha': str(lote.fecha_pago),
             'origen': snapshot(lote.cuenta_origen) if lote.cuenta_origen_id else None,
             'pagos': [{'id': p.id, 'incluido': p.incluido, 'valor': str(p.valor),
                        'cuenta': snapshot(p.cuenta) if p.cuenta_id else None,
                        'activa': p.cuenta.activa if p.cuenta_id else None,
                        'empleado_activo': p.empleado.activo if p.empleado_id else None,
                        'ce': [p.comprobante.estado, str(p.comprobante.valor), p.comprobante.cuenta_destino_id] if p.comprobante_id else None} for p in pagos]}
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def validar_cuenta(c):
    if c.banco not in BANCOS or c.tipo not in TIPOS or c.tipo_documento not in DOCUMENTOS:
        raise ErrorNegocio('Banco, producto o tipo de identificación inválido.')
    for campo in ('numero', 'documento'):
        if not re.fullmatch(r'[0-9]{1,16}', getattr(c, campo)):
            raise ErrorNegocio('Usa entre 1 y 16 dígitos, sin puntos, espacios ni guiones. El NIT debe incluir su dígito de verificación.', campo=campo)
    for campo in ('nombres', 'apellidos'):
        texto = getattr(c, campo)
        if not texto.strip() or len(texto) > 40 or not nombre_bancario(texto):
            raise ErrorNegocio('Completa nombre y apellido (o las dos partes de la razón social), máximo 40 caracteres cada uno.', campo=campo)
    if c.tipo in ('DP', 'TP') and c.banco != '51':
        raise ErrorNegocio('DaviPlata y Tarjeta Prepago deben usar el banco Davivienda.')
    if c.empresa and (c.banco not in ('51', '7') or c.tipo not in ('CA', 'CC')):
        raise ErrorNegocio('La cuenta de origen debe ser de ahorros o corriente de Davivienda o Bancolombia.')


def _dueno(proveedor=None, empleado=None, empresa=False, proveedor_tela=None):
    if sum([bool(proveedor), bool(empleado), bool(empresa), bool(proveedor_tela)]) != 1:
        raise ErrorNegocio('Selecciona un único beneficiario de la cuenta.')
    dueno = {'proveedor_id': None, 'proveedor_tela_id': None, 'empleado_id': None, 'empresa': False}
    if proveedor:
        dueno['proveedor_id'] = get_object_or_404(Proveedor.objects.select_for_update(), pk=entero(proveedor)).id
    elif proveedor_tela:
        dueno['proveedor_tela_id'] = get_object_or_404(ProveedorTela.objects.select_for_update(), pk=entero(proveedor_tela)).id
    elif empleado:
        dueno['empleado_id'] = get_object_or_404(EmpleadoPago.objects.select_for_update(), pk=entero(empleado)).id
    else:
        ProgramacionNomina.objects.select_for_update().get(pk=1)
        dueno['empresa'] = True
    return dueno


@transaction.atomic
def guardar_cuenta(usuario, datos, pk=None):
    dueno = _dueno(datos.get('proveedor'), datos.get('empleado'), datos.get('empresa') is True, datos.get('proveedor_tela'))
    c = get_object_or_404(CuentaBancaria.objects.select_for_update().filter(**dueno), pk=pk) if pk else CuentaBancaria(**dueno)
    if pk:
        revisar_revision(c, datos)
    for campo in ('alias', 'banco', 'tipo', 'numero', 'tipo_documento', 'documento', 'nombres', 'apellidos'):
        if campo in datos:
            setattr(c, campo, str(datos[campo] or '').strip())
    if len(c.alias) > 80:
        raise ErrorNegocio('El alias admite hasta 80 caracteres.')
    for campo in ('principal', 'activa'):
        if campo in datos:
            setattr(c, campo, booleano(datos[campo]))
    validar_cuenta(c)
    repetida = CuentaBancaria.objects.filter(**dueno, banco=c.banco, tipo=c.tipo, numero=c.numero).exclude(pk=c.pk)
    if repetida.exists():
        raise ErrorNegocio('Este titular ya tiene registrada esa cuenta.', 409)
    if c.principal and c.activa:
        CuentaBancaria.objects.filter(**dueno, principal=True).exclude(pk=c.pk).update(principal=False, revision=F('revision') + 1)
    c.principal = c.principal and c.activa
    c.revision += 1
    c.save()
    # La bitácora evita copiar números completos/documentos a logs de uso general.
    auditar(usuario, 'pagos.cuenta_guardada', c, {'banco': c.banco, 'ultimos': c.numero[-4:], 'activa': c.activa})
    return c


@transaction.atomic
def guardar_empleado(usuario, datos, pk=None):
    e = get_object_or_404(EmpleadoPago.objects.select_for_update(), pk=pk) if pk else EmpleadoPago()
    if not pk and not datos.get('usuario'):
        raise ErrorNegocio('Selecciona el usuario de la plataforma al que corresponde esta nómina.')
    e.nombre = str(datos.get('nombre', e.nombre) or '').strip()
    if not e.nombre or len(e.nombre) > 160:
        raise ErrorNegocio('Escribe el nombre del empleado (hasta 160 caracteres).')
    if 'usuario' in datos:
        uid = entero(datos['usuario']) if datos['usuario'] else None
        if e.usuario_id and uid != e.usuario_id:
            raise ErrorNegocio('El empleado ya está vinculado a un usuario. No se puede reasignar su historial y sus cuentas a otra persona.')
        if uid:
            get_object_or_404(CustomUser, pk=uid, is_active=True)
            if EmpleadoPago.objects.filter(usuario_id=uid).exclude(pk=e.pk).exists():
                raise ErrorNegocio('Este usuario ya tiene un empleado asociado.', 409)
        e.usuario_id = uid
    e.pago_mensual = pesos(datos.get('pago_mensual', e.pago_mensual), cero=True)
    if 'activo' in datos:
        e.activo = booleano(datos['activo'])
    e.save()
    auditar(usuario, 'pagos.empleado_guardado', e, {'pago_mensual': str(e.pago_mensual), 'activo': e.activo})
    return e


def cuenta_ce(cuenta_id, proveedor_id, medio, proveedor_tela_id=None):
    if not cuenta_id:
        return None
    c = get_object_or_404(CuentaBancaria.objects.select_for_update(), pk=entero(cuenta_id))
    if medio != 'Transferencia' or not c.activa or not ((proveedor_id and c.proveedor_id == int(proveedor_id)) or (proveedor_tela_id and c.proveedor_tela_id == int(proveedor_tela_id))):
        raise ErrorNegocio('La cuenta destino debe estar activa y pertenecer al proveedor de esta transferencia.', campo='cuenta_destino')
    validar_cuenta(c)
    return c


def proteger_ce(ce):
    if ce.pagos_bancarios.filter(incluido=True, rechazado=False, lote__estado='exportado').exists():
        raise ErrorNegocio('Este egreso está en un archivo bancario generado. Confirma el pago con la acción de confirmación o anula el lote antes de editarlo.', 409)


def _cuenta_empleado(e):
    cuentas = list(e.cuentas.all())
    activas = [c for c in cuentas if c.activa]
    principales = [c for c in activas if c.principal]
    return principales[0] if len(principales) == 1 else activas[0] if len(activas) == 1 else None


@transaction.atomic
def preparar_nomina(usuario, periodo, cuenta_origen=None, dia=25):
    try:
        primero = date.fromisoformat(str(periodo) + '-01')
    except (ValueError, TypeError):
        raise ErrorNegocio('Selecciona el mes de la nómina (AAAA-MM).')
    # También serializa las creaciones manuales y las del proceso programado.
    ProgramacionNomina.objects.select_for_update().get(pk=1)
    clave = 'mensual:' + primero.strftime('%Y-%m')
    existente = LotePago.objects.filter(clave_nomina=clave).first()
    if existente:
        return existente
    empleados = list(EmpleadoPago.objects.filter(activo=True).prefetch_related('cuentas'))
    if not empleados:
        raise ErrorNegocio('Agrega al menos un empleado activo antes de preparar la nómina.')
    fecha_pago = primero.replace(day=min(int(dia), calendar.monthrange(primero.year, primero.month)[1]))
    lote = LotePago.objects.create(tipo='nomina', nombre='Nómina ' + primero.strftime('%Y-%m'), fecha_pago=fecha_pago,
                                  cuenta_origen_id=cuenta_origen, clave_nomina=clave, creado_por=usuario)
    DetallePago.objects.bulk_create([DetallePago(lote=lote, empleado=e, cuenta=_cuenta_empleado(e), valor=e.pago_mensual,
                                               concepto='Pago mensual ' + primero.strftime('%Y-%m')) for e in empleados])
    auditar(usuario, 'pagos.nomina_preparada', lote, {'periodo': periodo, 'empleados': len(empleados)})
    return lote


@transaction.atomic
def crear_lote(usuario, datos, egresos_visibles):
    tipo = datos.get('tipo')
    if tipo == 'nomina':
        cfg = ProgramacionNomina.objects.get(pk=1)
        return preparar_nomina(usuario, datos.get('periodo'), cfg.cuenta_origen_id, cfg.dia)
    if tipo != 'proveedores':
        raise ErrorNegocio('Tipo de lote inválido.')
    ids = datos.get('comprobantes', [])
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise ErrorNegocio('Selecciona de 1 a 500 comprobantes.')
    ids = [entero(i) for i in ids]
    if len(set(ids)) != len(ids):
        raise ErrorNegocio('Hay comprobantes repetidos.')
    ces = list(egresos_visibles.prefetch_related(None).select_for_update().filter(id__in=ids).order_by('id'))
    # Bloquear los maestros antes de comparar las cuentas revisadas.
    list(CuentaBancaria.objects.select_for_update().filter(Q(proveedor_id__in=[c.proveedor_id for c in ces if c.proveedor_id]) | Q(proveedor_tela_id__in=[c.proveedor_tela_id for c in ces if c.proveedor_tela_id])).order_by('id'))
    prefetch_related_objects(ces, 'proveedor__cuentas_bancarias', 'proveedor_tela__cuentas_bancarias',
                             'facturas__items_inventario__referencia', 'facturas__items_inventario__categoria', 'facturas__items_inventario__subcategoria')
    if len(ces) != len(ids):
        raise ErrorNegocio('Algún comprobante no existe o no está disponible.')
    ocupados = set(DetallePago.objects.filter(comprobante_id__in=ids, incluido=True, rechazado=False).exclude(lote__estado='anulado').values_list('comprobante_id', flat=True))
    for ce in ces:
        if ce.medio_pago != 'Transferencia' or ce.estado != 'Por Confirmar Pago' or not (ce.proveedor_id or ce.proveedor_tela_id):
            raise ErrorNegocio(f'El CE {ce.id} debe ser una transferencia pendiente a un proveedor registrado.')
        if ce.id in ocupados:
            raise ErrorNegocio(f'El CE {ce.id} ya está en otro lote activo.', 409)
    revisados = datos.get('pagos')
    if revisados is not None:
        if not isinstance(revisados, list) or len(revisados) != len(ces) or any(not isinstance(d, dict) for d in revisados):
            raise ErrorNegocio('Revisa todas las cuentas de los comprobantes seleccionados.')
        por_ce = {entero(d.get('comprobante')): d for d in revisados}
        if set(por_ce) != set(ids):
            raise ErrorNegocio('La selección revisada no coincide con los comprobantes.')
        for ce in ces:
            d = por_ce[ce.id]
            if d.get('huella') != huella_ce(ce):
                raise ErrorNegocio(f'El CE {ce.id}, sus productos o sus cuentas cambiaron. Actualiza la revisión.', 409)
            c = cuenta_ce(d.get('cuenta'), ce.proveedor_id, ce.medio_pago, ce.proveedor_tela_id)
            if not c:
                raise ErrorNegocio(f'Selecciona la cuenta destino del CE {ce.id}.')
            ce.cuenta_destino = c
            ce.cuenta_destino_snapshot = snapshot(c)
        ComprobanteEgreso.objects.bulk_update(ces, ['cuenta_destino', 'cuenta_destino_snapshot'])
    lote = LotePago.objects.create(tipo=tipo, nombre=str(datos.get('nombre') or 'Pago a proveedores')[:120],
                                  fecha_pago=fecha(datos.get('fecha_pago')), creado_por=usuario)
    DetallePago.objects.bulk_create([DetallePago(lote=lote, comprobante=ce, cuenta_id=ce.cuenta_destino_id, valor=ce.valor, concepto=ce.concepto) for ce in ces])
    if datos.get('cuenta_origen'):
        guardar_lote(lote.id, usuario, {'revision': lote.revision, 'cuenta_origen': datos['cuenta_origen']})
        lote.refresh_from_db()
    auditar(usuario, 'pagos.lote_creado', lote, {'comprobantes': ids})
    return lote


@transaction.atomic
def guardar_lote(pk, usuario, datos):
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    revisar_revision(lote, datos)
    if lote.estado != 'borrador':
        raise ErrorNegocio('Solo se pueden editar lotes en borrador.', 409)
    if 'fecha_pago' in datos:
        lote.fecha_pago = fecha(datos['fecha_pago'])
    if 'nombre' in datos:
        lote.nombre = str(datos['nombre'] or '').strip()
        if not lote.nombre or len(lote.nombre) > 120:
            raise ErrorNegocio('Escribe un nombre de hasta 120 caracteres.')
    if 'cuenta_origen' in datos:
        origen = get_object_or_404(CuentaBancaria, pk=entero(datos['cuenta_origen'])) if datos['cuenta_origen'] else None
        if origen and (not origen.empresa or not origen.activa):
            raise ErrorNegocio('Selecciona una cuenta de origen activa de la empresa.')
        lote.cuenta_origen = origen
        lote.banco_origen = 'bancolombia' if origen and origen.banco == '7' else 'davivienda'
    lineas = datos.get('pagos', [])
    if not isinstance(lineas, list) or len(lineas) > 500:
        raise ErrorNegocio('Formato de pagos inválido.')
    vistas = set()
    pagos_por_id = {p.id: p for p in lote.pagos.all()}
    cuentas_ids = {entero(d['cuenta']) for d in lineas if isinstance(d, dict) and d.get('cuenta')}
    cuentas_por_id = {c.id: c for c in CuentaBancaria.objects.filter(pk__in=cuentas_ids)}
    ce_ids = [p.comprobante_id for p in pagos_por_id.values() if p.comprobante_id]
    ces = {c.id: c for c in ComprobanteEgreso.objects.select_for_update().filter(pk__in=ce_ids).order_by('id')}
    bloqueados = set(DetallePago.objects.filter(comprobante_id__in=ce_ids, incluido=True, rechazado=False, lote__estado='exportado').values_list('comprobante_id', flat=True))
    cambiados, ces_cambiados = [], {}
    for d in lineas:
        if not isinstance(d, dict):
            raise ErrorNegocio('Formato de pago inválido.')
        identificador = entero(d.get('id'))
        if identificador in vistas:
            raise ErrorNegocio('Hay pagos repetidos.')
        vistas.add(identificador)
        p = pagos_por_id.get(identificador)
        if not p:
            raise ErrorNegocio('Un pago no pertenece a este lote.', 404)
        if 'valor' in d:
            valor = pesos(d['valor'], cero=True)
            if lote.tipo != 'nomina' and valor != p.valor:
                raise ErrorNegocio('El importe del proveedor se modifica en su comprobante de egreso.')
            p.valor = valor
        if 'incluido' in d:
            p.incluido = booleano(d['incluido'])
        if 'cuenta' in d:
            c = cuentas_por_id.get(entero(d['cuenta'])) if d['cuenta'] else None
            if d['cuenta'] and not c:
                raise ErrorNegocio('Cuenta no encontrada.', 404)
            if c and (not c.activa or (p.empleado_id and c.empleado_id != p.empleado_id) or (p.comprobante_id and not p.empleado_id and not pertenece(c, ces[p.comprobante_id]))):
                raise ErrorNegocio('La cuenta no pertenece al beneficiario de este pago.')
            p.cuenta = c
            if p.comprobante_id:
                ce = ces[p.comprobante_id]
                if ce.id in bloqueados:
                    raise ErrorNegocio('El egreso está en un archivo bancario generado.', 409)
                if ce.estado != 'Por Confirmar Pago' or (c and not p.empleado_id and not pertenece(c, ce)):
                    raise ErrorNegocio('El comprobante cambió. Revisa el lote.', 409)
                ce.cuenta_destino = c
                ce.cuenta_destino_snapshot = snapshot(c) if c else {}
                ces_cambiados[ce.id] = ce
        cambiados.append(p)
    if cambiados:
        DetallePago.objects.bulk_update(cambiados, ['cuenta', 'valor', 'incluido'])
    if ces_cambiados:
        ComprobanteEgreso.objects.bulk_update(list(ces_cambiados.values()), ['cuenta_destino', 'cuenta_destino_snapshot'])
    lote.revision += 1
    lote.save()
    auditar(usuario, 'pagos.lote_editado', lote, {'revision': lote.revision})
    return lote


def problemas_lote(lote, pagos):
    errores = []
    origen = lote.cuenta_origen
    if not origen or not origen.empresa or not origen.activa:
        errores.append('Selecciona una cuenta de origen activa de la empresa.')
    elif origen.banco != '51' or lote.banco_origen != 'davivienda':
        errores.append('La exportación está habilitada desde Davivienda. El formato de origen Bancolombia está pendiente.')
    if lote.fecha_pago < timezone.localdate():
        errores.append('Actualiza la fecha de pago: no puede estar en el pasado.')
    incluidos = [p for p in pagos if p.incluido]
    if not incluidos:
        errores.append('Incluye al menos un pago.')
    for p in incluidos:
        etiqueta = f'CE {p.comprobante_id}' if lote.tipo == 'proveedores' else (p.empleado.nombre if p.empleado_id else f'Pago {p.id}')
        if p.valor <= 0 or p.valor != p.valor.to_integral_value() or p.valor > MAX_CE:
            errores.append(f'{etiqueta}: introduce un importe entero positivo (hasta $99.999.999).')
        c = p.cuenta
        if not c or not c.activa:
            errores.append(f'{etiqueta}: selecciona una cuenta destino activa.')
        elif (p.empleado_id and c.empleado_id != p.empleado_id) or (lote.tipo == 'proveedores' and not pertenece(c, p.comprobante)):
            errores.append(f'{etiqueta}: la cuenta no pertenece al beneficiario.')
        else:
            try:
                validar_cuenta(c)
            except ErrorNegocio as exc:
                errores.append(f'{etiqueta}: {exc.mensaje}')
        if p.empleado_id and not p.empleado.activo:
            errores.append(f'{etiqueta}: el empleado está inactivo.')
        if lote.tipo == 'proveedores':
            ce = p.comprobante
            if not ce or ce.estado != 'Por Confirmar Pago' or ce.medio_pago != 'Transferencia' or ce.valor != p.valor or ce.cuenta_destino_id != p.cuenta_id:
                errores.append(f'{etiqueta}: el comprobante cambió o ya está pagado. Retíralo y crea otro lote con sus datos actuales.')
    return errores


@transaction.atomic
def generar_archivo(pk, usuario, revision, huella=None):
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    if lote.estado == 'anulado':
        raise ErrorNegocio('Este lote está anulado.', 409)
    if lote.estado == 'exportado':
        return lote
    revisar_revision(lote, {'revision': revision})
    pagos = list(lote.pagos.select_related('comprobante', 'empleado', 'cuenta').all())
    ids_ce = [p.comprobante_id for p in pagos if p.comprobante_id]
    ces = {ce.id: ce for ce in ComprobanteEgreso.objects.select_for_update().filter(id__in=ids_ce).order_by('id')}
    ids_cuentas = [p.cuenta_id for p in pagos if p.cuenta_id] + ([lote.cuenta_origen_id] if lote.cuenta_origen_id else [])
    empleados = {e.id: e for e in EmpleadoPago.objects.select_for_update().filter(id__in=[p.empleado_id for p in pagos if p.empleado_id]).order_by('id')}
    cuentas = {c.id: c for c in CuentaBancaria.objects.select_for_update().filter(id__in=ids_cuentas).order_by('id')}
    lote.cuenta_origen = cuentas.get(lote.cuenta_origen_id)
    for p in pagos:
        p.cuenta = cuentas.get(p.cuenta_id)
        if p.comprobante_id:
            p.comprobante = ces[p.comprobante_id]
        if p.empleado_id:
            p.empleado = empleados[p.empleado_id]
    problemas = problemas_lote(lote, pagos)
    if problemas:
        raise ErrorNegocio(' '.join(problemas), campo='validaciones')
    if huella != huella_lote(lote, pagos):
        raise ErrorNegocio('Una cuenta o egreso cambió desde la revisión. Recarga el lote y verifica los datos antes de descargar.', 409)
    incluidos_ce = [p.comprobante_id for p in pagos if p.comprobante_id and p.incluido]
    if DetallePago.objects.filter(comprobante_id__in=incluidos_ce, incluido=True, rechazado=False).exclude(lote=lote).exclude(lote__estado='anulado').exists():
        raise ErrorNegocio('Un comprobante ya está reservado en otro lote.', 409)
    filas, ces_actualizados, detalles_actualizados = [], [], []
    for p in pagos:
        if not p.incluido:
            continue
        p.cuenta_snapshot = snapshot(p.cuenta)
        if lote.tipo == 'nomina':
            if p.comprobante_id:
                if p.comprobante.estado != 'Por Confirmar Pago':
                    raise ErrorNegocio('Este pago de nómina ya fue confirmado.', 409)
                ce = p.comprobante
                ce.valor, ce.fecha, ce.cuenta_destino, ce.cuenta_destino_snapshot = p.valor, lote.fecha_pago, p.cuenta, p.cuenta_snapshot
                ces_actualizados.append(ce)
            else:
                numero = siguiente_consecutivo('comprobante_egreso', 3001, ComprobanteEgreso.objects.aggregate(Max('id'))['id__max'] or 0)
                p.comprobante = ComprobanteEgreso.objects.create(
                    id=numero, proveedor_otro_nombre=p.empleado.nombre, recibido_por=p.empleado.nombre,
                    medio_pago='Transferencia', estado='Por Confirmar Pago', valor=p.valor, fecha=lote.fecha_pago,
                    concepto=p.concepto, creado_por=usuario, cuenta_destino=p.cuenta,
                    cuenta_destino_snapshot=p.cuenta_snapshot,
                )
                auditar(usuario, 'pagos.egreso_nomina_creado', p.comprobante, {'lote': lote.id, 'empleado': p.empleado_id})
        else:
            p.comprobante.cuenta_destino = p.cuenta
            p.comprobante.cuenta_destino_snapshot = p.cuenta_snapshot
            ces_actualizados.append(p.comprobante)
        detalles_actualizados.append(p)
        filas.append({'cuenta': p.cuenta_snapshot, 'valor': p.valor, 'referencia': p.comprobante_id})
    if ces_actualizados:
        ComprobanteEgreso.objects.bulk_update(ces_actualizados, ['valor', 'fecha', 'cuenta_destino', 'cuenta_destino_snapshot'])
    DetallePago.objects.bulk_update(detalles_actualizados, ['cuenta_snapshot', 'comprobante'])
    contenido = exportar(lote.banco_origen, filas)
    lote.archivo = contenido
    lote.archivo_sha256 = hashlib.sha256(contenido).hexdigest()
    lote.origen_snapshot = snapshot(lote.cuenta_origen)
    lote.estado = 'exportado'
    lote.exportado_en = timezone.now()
    lote.revision += 1
    lote.save()
    ArchivoLotePago.objects.create(lote=lote, revision=lote.revision, contenido=contenido, sha256=lote.archivo_sha256,
                                  datos={'origen': lote.origen_snapshot, 'pagos': [{**f, 'valor': str(f['valor'])} for f in filas]})
    auditar(usuario, 'pagos.archivo_generado', lote, {'sha256': lote.archivo_sha256, 'pagos': len(filas), 'total': str(sum(f['valor'] for f in filas))})
    return lote


@transaction.atomic
def anular_lote(pk, usuario, datos):
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    revisar_revision(lote, datos)
    motivo = str(datos.get('motivo') or '').strip()
    if not motivo or len(motivo) > 300:
        raise ErrorNegocio('Indica el motivo de anulación (hasta 300 caracteres).')
    if lote.estado == 'anulado':
        return lote
    if lote.pagos.filter(incluido=True, comprobante__estado='Pagado').exists():
        raise ErrorNegocio('El lote tiene pagos confirmados. No puede anularse.', 409)
    if lote.estado == 'exportado' and datos.get('archivo_no_procesado') is not True:
        raise ErrorNegocio('Confirma que el archivo no fue procesado ni quedó programado en el banco.')
    lote.estado = 'anulado'
    lote.motivo_anulacion = motivo
    lote.revision += 1
    lote.save(update_fields=['estado', 'motivo_anulacion', 'revision'])
    auditar(usuario, 'pagos.lote_anulado', lote, {'motivo': motivo, 'archivo_no_procesado': datos.get('archivo_no_procesado')})
    return lote


@transaction.atomic
def corregir_lote(pk, usuario, datos):
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    revisar_revision(lote, datos)
    if lote.estado != 'anulado':
        raise ErrorNegocio('Solo se puede corregir un lote anulado.', 409)
    if lote.pagos.filter(rechazado=True).exists():
        raise ErrorNegocio('Este lote ya tiene reintentos. Corrige el lote de reintento para conservar la trazabilidad.', 409)
    ids = list(lote.pagos.filter(incluido=True, comprobante__isnull=False).values_list('comprobante_id', flat=True))
    ces = list(ComprobanteEgreso.objects.select_for_update().filter(pk__in=ids).order_by('id'))
    if any(c.estado == 'Pagado' for c in ces):
        raise ErrorNegocio('Hay egresos ya pagados. No se puede corregir este lote.', 409)
    if DetallePago.objects.filter(incluido=True, rechazado=False, comprobante_id__in=ids).exclude(lote=lote).exclude(lote__estado='anulado').exists():
        raise ErrorNegocio('Algún egreso ya está incluido en otro lote activo.', 409)
    lote.estado, lote.archivo, lote.archivo_sha256, lote.exportado_en = 'borrador', None, '', None
    lote.revision += 1
    lote.save(update_fields=['estado', 'archivo', 'archivo_sha256', 'exportado_en', 'revision'])
    auditar(usuario, 'pagos.lote_corregir', lote, {'revision': lote.revision})
    return lote


@transaction.atomic
def confirmar_pagos(pk, usuario, datos):
    from ordenes.servicios import confirmar_pago_egreso
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    if lote.estado != 'exportado':
        raise ErrorNegocio('Solo se confirman pagos de un archivo generado.', 409)
    ids = datos.get('comprobantes')
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise ErrorNegocio('Selecciona los pagos que el banco realizó.')
    ids = {entero(i) for i in ids}
    disponibles = set(lote.pagos.filter(incluido=True, rechazado=False).values_list('comprobante_id', flat=True))
    if not ids.issubset(disponibles):
        raise ErrorNegocio('Solo se pueden confirmar egresos incluidos en este archivo.')
    referencia = str(datos.get('referencia') or '').strip()
    if not referencia or len(referencia) > 120:
        raise ErrorNegocio('Escribe la referencia o número de operación del banco (hasta 120 caracteres).')
    ces = list(ComprobanteEgreso.objects.select_for_update().filter(pk__in=ids).order_by('id'))
    if any(c.medio_pago != 'Transferencia' or c.estado not in ('Pagado', 'Por Confirmar Pago') for c in ces):
        raise ErrorNegocio('Algún egreso cambió. Revisa los pagos antes de confirmar.', 409)
    for ce in ces:
        confirmar_pago_egreso(ce, usuario)
    auditar(usuario, 'pagos.confirmar', lote, {'comprobantes': sorted(ids), 'referencia_banco': referencia})
    return lote


@transaction.atomic
def reintentar_pagos(pk, usuario, datos):
    """Rechazo confirmado por el operador: conserva el archivo y reutiliza CE.

    Nunca reintentar un pago que el banco aún tiene pendiente o programado.
    """
    lote = get_object_or_404(LotePago.objects.select_for_update(), pk=pk)
    revisar_revision(lote, datos)
    if lote.estado != 'exportado' or datos.get('rechazo_confirmado') is not True:
        raise ErrorNegocio('Confirma en el banco que los pagos seleccionados fueron rechazados y no están pendientes ni programados.')
    ref = str(datos.get('referencia') or '').strip()
    if not ref or len(ref) > 120:
        raise ErrorNegocio('Indica la referencia del resultado bancario (hasta 120 caracteres).')
    raw = datos.get('comprobantes')
    if not isinstance(raw, list) or not raw or len(raw) > 500:
        raise ErrorNegocio('Selecciona los pagos rechazados.')
    ids = {entero(i) for i in raw}
    pagos = list(lote.pagos.filter(incluido=True, rechazado=False, comprobante_id__in=ids).select_related('cuenta'))
    if len(pagos) != len(ids):
        raise ErrorNegocio('Algún pago ya tiene reintento o no pertenece a este archivo.', 409)
    ces = list(ComprobanteEgreso.objects.select_for_update().filter(pk__in=ids).order_by('id'))
    if any(c.estado != 'Por Confirmar Pago' for c in ces):
        raise ErrorNegocio('No se puede reintentar un egreso confirmado.', 409)
    nuevo = LotePago.objects.create(tipo=lote.tipo, nombre=f'Reintento de lote {lote.id}', fecha_pago=timezone.localdate(),
                                    banco_origen=lote.banco_origen, cuenta_origen=lote.cuenta_origen, creado_por=usuario)
    DetallePago.objects.filter(pk__in=[p.id for p in pagos]).update(rechazado=True)
    DetallePago.objects.bulk_create([DetallePago(lote=nuevo, comprobante_id=p.comprobante_id, empleado_id=p.empleado_id,
                                                cuenta_id=p.cuenta_id, valor=p.valor, concepto=p.concepto) for p in pagos])
    lote.revision += 1
    lote.save(update_fields=['revision'])
    auditar(usuario, 'pagos.reintento', lote, {'nuevo_lote': nuevo.id, 'referencia_banco': ref, 'comprobantes': sorted(ids)})
    return nuevo


@transaction.atomic
def guardar_programacion(usuario, datos):
    cfg = ProgramacionNomina.objects.select_for_update().get(pk=1)
    revisar_revision(cfg, datos)
    dia = entero(datos.get('dia', cfg.dia))
    if not 1 <= dia <= 31:
        raise ErrorNegocio('El día debe estar entre 1 y 31.')
    activa = booleano(datos.get('activa', cfg.activa))
    cid = datos.get('cuenta_origen', cfg.cuenta_origen_id)
    c = get_object_or_404(CuentaBancaria, pk=entero(cid)) if cid else None
    if activa and (not c or not c.empresa or not c.activa or c.banco != '51'):
        raise ErrorNegocio('Para activar la preparación automática elige una cuenta de origen Davivienda activa.')
    if activa and not cfg.activa:
        cfg.habilitada_desde = timezone.localdate()
    cfg.activa, cfg.dia, cfg.cuenta_origen, cfg.actualizado_por = activa, dia, c, usuario
    cfg.revision += 1
    cfg.save()
    auditar(usuario, 'pagos.programacion_guardada', cfg, {'activa': activa, 'dia': dia})
    return cfg


def preparar_programada(hoy=None):
    """Recupera el mes actual si el motor estuvo apagado el día previsto.

    No prepara meses previos, no descarga archivos, no confirma pagos y nunca
    recalcula un borrador existente (preserva los cambios hechos a mano).
    """
    hoy = hoy or timezone.localdate()
    with transaction.atomic():
        cfg = ProgramacionNomina.objects.select_for_update().filter(pk=1).first()
        if not cfg or not cfg.activa or not cfg.habilitada_desde or hoy < cfg.habilitada_desde:
            return None
        dia = min(cfg.dia, calendar.monthrange(hoy.year, hoy.month)[1])
        if hoy.day < dia:
            return None
        lote = preparar_nomina(cfg.actualizado_por, hoy.strftime('%Y-%m'), cfg.cuenta_origen_id, dia)
        cfg.ultimo_intento, cfg.ultimo_error = timezone.now(), ''
        cfg.save(update_fields=['ultimo_intento', 'ultimo_error'])
        return lote


@transaction.atomic
def asociar_beneficiario_ce(usuario, pk, datos):
    ce = get_object_or_404(ComprobanteEgreso.objects.select_for_update(), pk=pk)
    if ce.estado != 'Por Confirmar Pago' or ce.medio_pago != 'Transferencia':
        raise ErrorNegocio('Solo puedes asociar transferencias pendientes.', 409)
    if ce.pagos_bancarios.filter(incluido=True, rechazado=False).exclude(lote__estado='anulado').exists():
        raise ErrorNegocio('Este CE ya está en una agrupación de pagos. Ábrela para revisar su cuenta.', 409)
    if datos.get('huella') != huella_ce(ce):
        raise ErrorNegocio('El comprobante cambió. Actualiza la tabla antes de asociarlo.', 409)
    if not ce.proveedor_id and not ce.proveedor_tela_id:
        if ce.facturas.exists():
            raise ErrorNegocio('Revisa el proveedor de las facturas antes de asociar este CE.')
        if bool(datos.get('proveedor')) == bool(datos.get('proveedor_tela')):
            raise ErrorNegocio('Selecciona un proveedor o proveedor de telas.')
        if datos.get('proveedor'):
            ce.proveedor = get_object_or_404(Proveedor, pk=entero(datos['proveedor']))
        else:
            ce.proveedor_tela = get_object_or_404(ProveedorTela, pk=entero(datos['proveedor_tela']))
    c = cuenta_ce(datos.get('cuenta'), ce.proveedor_id, ce.medio_pago, ce.proveedor_tela_id)
    ce.cuenta_destino = c
    ce.cuenta_destino_snapshot = snapshot(c) if c else {}
    ce.save(update_fields=['proveedor', 'proveedor_tela', 'cuenta_destino', 'cuenta_destino_snapshot'])
    auditar(usuario, 'pagos.ce_beneficiario_asociado', ce, {'proveedor': ce.proveedor_id, 'proveedor_tela': ce.proveedor_tela_id})
    from ordenes.serializers import ComprobanteEgresoSerializer
    from .beneficiarios import preparar_consulta
    return ComprobanteEgresoSerializer(preparar_consulta(ComprobanteEgreso.objects.filter(pk=pk), {}).get()).data
