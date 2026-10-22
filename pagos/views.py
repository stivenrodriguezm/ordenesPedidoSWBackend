from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from ordenes.consultas_reportes import consultar_comprobantes_egreso
from ordenes.models import CustomUser, AsesorNomina, Proveedor, ProveedorTela, ComprobanteEgreso
from ordenes.permissions import tiene_permiso_codigo
from ordenes.servicios import ErrorNegocio, idempotente
from . import servicios as s
from .beneficiarios import nombre_ce, titular_ce, huella_ce
from .catalogo import BANCOS, DOCUMENTOS, TIPOS
from .exportadores import nombre_bancario
from .models import CuentaBancaria, EmpleadoPago, LotePago, DetallePago, ProgramacionNomina


def exigir(request, *codigos):
    if not any(tiene_permiso_codigo(request, p) for p in codigos):
        raise ErrorNegocio('No tienes permiso para esta operación.', 403)


def permiso_tipo(request, tipo, escribir=False, exportar=False):
    if tipo == 'nomina':
        exigir(request, 'GESTIONAR_NOMINA' if escribir or exportar else 'VER_NOMINA')
    elif tipo == 'proveedores':
        exigir(request, 'CREAR_COMPROBANTE_EGRESO' if escribir else 'VER_COMPROBANTES_EGRESO')
        # Los lotes comparten varios egresos: no exponer los de otros autores a
        # roles restringidos a propios, aunque conozcan el ID de un lote.
        exigir(request, 'VER_TODOS_EGRESOS')
        if exportar:
            exigir(request, 'EXPORTAR_EGRESOS')
    else:
        raise ErrorNegocio('Tipo de lote inválido.')


# Los permisos se evalúan antes de consultar una respuesta idempotente.
class PermisoCuentas(BasePermission):
    def has_permission(self, request, view):
        titular_cuenta(request, request.query_params if request.method == 'GET' else request.data, request.method != 'GET')
        return True


class PermisoEmpleados(BasePermission):
    def has_permission(self, request, view):
        exigir(request, 'VER_NOMINA' if request.method == 'GET' else 'GESTIONAR_NOMINA')
        return True


class PermisoLotes(BasePermission):
    def has_permission(self, request, view):
        tipo = request.query_params.get('tipo', 'proveedores') if request.method == 'GET' else request.data.get('tipo')
        permiso_tipo(request, tipo, escribir=request.method != 'GET')
        return True


class PermisoReintento(BasePermission):
    def has_permission(self, request, view):
        obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=view.kwargs['pk'])
        permiso_tipo(request, obj.tipo, escribir=True)
        return True


def cuenta_dict(c):
    return {**s.snapshot(c), 'proveedor': c.proveedor_id, 'proveedor_tela': c.proveedor_tela_id, 'empleado': c.empleado_id, 'empresa': c.empresa,
            'principal': c.principal, 'activa': c.activa, 'revision': c.revision,
            'banco_nombre': BANCOS.get(c.banco, c.banco),
            'nombre_archivo': nombre_bancario(c.nombres) + ' ' + nombre_bancario(c.apellidos)}


def empleado_dict(e):
    return {'id': e.id, 'nombre': e.nombre, 'usuario': e.usuario_id, 'pago_mensual': str(e.pago_mensual),
            'activo': e.activo, 'cuentas': [cuenta_dict(c) for c in e.cuentas.all()]}


def consulta_lotes():
    return LotePago.objects.defer('archivo').select_related('cuenta_origen').prefetch_related(
        'pagos__cuenta', 'pagos__empleado', 'pagos__comprobante__proveedor', 'pagos__comprobante__proveedor_tela')


def lote_dict(lote, detalle=True):
    pagos = list(lote.pagos.all())
    incluidos = [p for p in pagos if p.incluido]
    d = {k: getattr(lote, k) for k in ('id', 'tipo', 'nombre', 'banco_origen', 'fecha_pago', 'estado', 'revision', 'creado_en', 'exportado_en', 'motivo_anulacion', 'archivo_sha256')}
    d.update({'cuenta_origen': lote.cuenta_origen_id, 'origen_snapshot': lote.origen_snapshot,
              'huella_revision': s.huella_lote(lote, pagos) if lote.estado == 'borrador' else None,
              'cantidad': len(incluidos), 'total': str(sum((p.valor for p in incluidos), 0)),
              'confirmados': sum(bool(not p.rechazado and p.comprobante_id and p.comprobante.estado == 'Pagado') for p in incluidos),
              'rechazados': sum(p.rechazado for p in incluidos),
              'validaciones': s.problemas_lote(lote, pagos) if lote.estado == 'borrador' else []})
    if detalle:
        d['pagos'] = [{
            'id': p.id, 'comprobante': p.comprobante_id, 'empleado': p.empleado_id,
            'proveedor': p.comprobante.proveedor_id if lote.tipo == 'proveedores' and p.comprobante_id else None,
            'titular': {'empleado': p.empleado_id} if p.empleado_id else titular_ce(p.comprobante),
            'beneficiario': p.empleado.nombre if p.empleado_id else nombre_ce(p.comprobante),
            'valor': str(p.valor), 'incluido': p.incluido, 'cuenta': p.cuenta_id,
            'rechazado': p.rechazado,
            'cuenta_detalle': ((p.cuenta_snapshot if lote.estado != 'borrador' else None) or s.snapshot(p.cuenta)) if p.cuenta_id else None,
            'concepto': p.concepto, 'estado_pago': p.comprobante.estado if p.comprobante_id else 'Por Confirmar Pago',
        } for p in pagos]
    return d


def respuesta_lote(pk):
    return Response(lote_dict(consulta_lotes().get(pk=pk)))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def catalogo(request):
    exigir(request, 'VER_COMPROBANTES_EGRESO', 'VER_NOMINA', 'ADMINISTRAR_PROVEEDORES')
    return Response({'bancos': BANCOS, 'documentos': DOCUMENTOS, 'tipos': TIPOS,
                     'exportadores': [{'id': 'davivienda', 'nombre': 'Davivienda', 'disponible': True},
                                      {'id': 'bancolombia', 'nombre': 'Bancolombia', 'disponible': False}]})


def titular_cuenta(request, datos, escribir=False):
    if datos.get('empleado'):
        exigir(request, 'GESTIONAR_NOMINA' if escribir else 'VER_NOMINA')
        return {'empleado_id': s.entero(datos['empleado']), 'empresa': False}
    if datos.get('proveedor'):
        exigir(request, *(['ADMINISTRAR_PROVEEDORES', 'CREAR_COMPROBANTE_EGRESO'] if escribir else ['VER_COMPROBANTES_EGRESO', 'ADMINISTRAR_PROVEEDORES']))
        return {'proveedor_id': s.entero(datos['proveedor']), 'empresa': False}
    if datos.get('proveedor_tela'):
        exigir(request, *(['ADMINISTRAR_PROVEEDORES', 'CREAR_COMPROBANTE_EGRESO'] if escribir else ['VER_COMPROBANTES_EGRESO', 'ADMINISTRAR_PROVEEDORES']))
        return {'proveedor_tela_id': s.entero(datos['proveedor_tela']), 'empresa': False}
    if datos.get('empresa') in (True, '1', 'true'):
        exigir(request, *(['APROBAR_EGRESO', 'GESTIONAR_NOMINA'] if escribir else ['VER_COMPROBANTES_EGRESO', 'VER_NOMINA']))
        return {'empresa': True}
    raise ErrorNegocio('Selecciona el proveedor, proveedor de telas, empleado o cuenta de la empresa.')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, PermisoCuentas])
@idempotente('pagos.cuenta_crear')
def cuentas(request):
    if request.method == 'POST':
        titular_cuenta(request, request.data, True)
        c = s.guardar_cuenta(request.user, request.data)
        return Response(cuenta_dict(c), status=201)
    filtros = titular_cuenta(request, request.query_params)
    return Response([cuenta_dict(c) for c in CuentaBancaria.objects.filter(**filtros)])


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def cuenta(request, pk):
    titular_cuenta(request, request.data, True)
    datos = dict(request.data)
    if request.method == 'DELETE':
        datos.update(activa=False, principal=False)
    return Response(cuenta_dict(s.guardar_cuenta(request.user, datos, pk)))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, PermisoEmpleados])
@idempotente('pagos.empleado_crear')
def empleados(request):
    exigir(request, 'GESTIONAR_NOMINA' if request.method == 'POST' else 'VER_NOMINA')
    if request.method == 'POST':
        e = s.guardar_empleado(request.user, request.data)
        return Response(empleado_dict(e), status=201)
    fijos = {a.asesor_id: str(a.salario_basico) for a in AsesorNomina.objects.all()}
    usuarios = [{'id': u.id, 'nombre': (u.get_full_name() or u.username), 'basico': fijos.get(u.id, '0')}
                for u in CustomUser.objects.filter(is_active=True).order_by('first_name', 'username')]
    return Response({'empleados': [empleado_dict(e) for e in EmpleadoPago.objects.prefetch_related('cuentas')], 'usuarios': usuarios})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def empleado(request, pk):
    exigir(request, 'GESTIONAR_NOMINA')
    return Response(empleado_dict(s.guardar_empleado(request.user, request.data, pk)))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pendientes(request):
    permiso_tipo(request, 'proveedores')
    reservados = DetallePago.objects.filter(incluido=True, rechazado=False).exclude(lote__estado='anulado').values('comprobante_id')
    qs = consultar_comprobantes_egreso(request).prefetch_related(None).filter(medio_pago='Transferencia', estado='Por Confirmar Pago', ).filter(Q(proveedor__isnull=False) | Q(proveedor_tela__isnull=False)).exclude(pk__in=reservados.filter(comprobante__isnull=False))
    return Response([{'id': ce.id, 'proveedor': ce.proveedor_id, 'proveedor_nombre': nombre_ce(ce),
                      'fecha': ce.fecha, 'valor': str(ce.valor), 'concepto': ce.concepto,
                      'cuenta_destino': ce.cuenta_destino_snapshot} for ce in qs[:500]])


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, PermisoLotes])
@idempotente('pagos.lote_crear')
def lotes(request):
    tipo = request.data.get('tipo') if request.method == 'POST' else request.query_params.get('tipo', 'proveedores')
    permiso_tipo(request, tipo, escribir=request.method == 'POST')
    if request.method == 'POST':
        lote = s.crear_lote(request.user, request.data, consultar_comprobantes_egreso(request))
        return Response(lote_dict(consulta_lotes().get(pk=lote.pk)), status=201)
    return Response([lote_dict(l, detalle=False) for l in consulta_lotes().filter(tipo=tipo)[:100]])


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def lote(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo, escribir=request.method == 'PATCH')
    if request.method == 'PATCH':
        s.guardar_lote(pk, request.user, request.data)
    return respuesta_lote(pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def archivo(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo, escribir=True, exportar=True)
    obj = s.generar_archivo(pk, request.user, request.data.get('revision'), request.data.get('huella_revision'))
    r = HttpResponse(bytes(obj.archivo), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    r['Content-Disposition'] = f'attachment; filename="Davivienda_{obj.tipo}_{obj.id}.xlsx"'
    r['Cache-Control'] = 'private, no-store'
    r['X-Content-Type-Options'] = 'nosniff'
    return r


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def anular(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo, escribir=True)
    s.anular_lote(pk, request.user, request.data)
    return respuesta_lote(pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def corregir(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo, escribir=True)
    s.corregir_lote(pk, request.user, request.data)
    return respuesta_lote(pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirmar(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo)
    exigir(request, 'APROBAR_EGRESO')
    s.confirmar_pagos(pk, request.user, request.data)
    return respuesta_lote(pk)


@api_view(['POST'])
@permission_classes([IsAuthenticated, PermisoReintento])
@idempotente('pagos.reintentar')
def reintentar(request, pk):
    obj = get_object_or_404(LotePago.objects.only('id', 'tipo'), pk=pk)
    permiso_tipo(request, obj.tipo, escribir=True)
    nuevo = s.reintentar_pagos(pk, request.user, request.data)
    return respuesta_lote(nuevo.id)


def programacion_dict(c):
    return {k: getattr(c, k) for k in ('activa', 'dia', 'cuenta_origen_id', 'revision', 'ultimo_intento', 'ultimo_error', 'latido_motor')}


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def programacion(request):
    exigir(request, 'GESTIONAR_NOMINA' if request.method == 'PUT' else 'VER_NOMINA')
    c = s.guardar_programacion(request.user, request.data) if request.method == 'PUT' else ProgramacionNomina.objects.get(pk=1)
    return Response(programacion_dict(c))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def beneficiarios(request):
    proveedores = tiene_permiso_codigo(request, 'VER_COMPROBANTES_EGRESO') or tiene_permiso_codigo(request, 'ADMINISTRAR_PROVEEDORES')
    nomina = tiene_permiso_codigo(request, 'VER_NOMINA')
    if not proveedores and not nomina:
        raise ErrorNegocio('No tienes permiso para consultar beneficiarios.', 403)
    resultado = []
    if proveedores:
        for modelo, tipo, clave in [(Proveedor, 'Proveedor', 'proveedor'), (ProveedorTela, 'Proveedor de telas', 'proveedor_tela')]:
            for p in modelo.objects.order_by('nombre_empresa').prefetch_related('cuentas_bancarias'):
                cs = [c for c in p.cuentas_bancarias.all() if c.activa]
                resultado.append({'clave': f'{clave}:{p.id}', 'titular': {clave: p.id}, 'nombre': p.nombre_empresa,
                                  'tipo': tipo, 'cuentas': len(cs), 'bancos': sorted({BANCOS.get(c.banco, c.banco) for c in cs})})
    if nomina:
        for e in EmpleadoPago.objects.select_related('usuario').prefetch_related('cuentas'):
            cs = [c for c in e.cuentas.all() if c.activa]
            resultado.append({'clave': f'empleado:{e.id}', 'titular': {'empleado': e.id}, 'nombre': e.nombre,
                              'tipo': 'Nómina', 'usuario': e.usuario_id, 'usuario_nombre': (e.usuario.get_full_name() or e.usuario.username) if e.usuario_id else None, 'cuentas': len(cs),
                              'bancos': sorted({BANCOS.get(c.banco, c.banco) for c in cs})})
    return Response(resultado)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def revisar_ce(request):
    permiso_tipo(request, 'proveedores')
    from ordenes.serializers import ComprobanteEgresoSerializer
    ids = request.data.get('comprobantes')
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise ErrorNegocio('Selecciona entre 1 y 500 CE.')
    ids = [s.entero(i) for i in ids]
    qs = consultar_comprobantes_egreso(request).filter(pk__in=ids)
    ces = list(qs)
    if len(ces) != len(set(ids)):
        raise ErrorNegocio('Hay comprobantes que ya no están disponibles.', 409)
    return Response(ComprobanteEgresoSerializer(ces, many=True).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def asociar_ce(request, pk):
    permiso_tipo(request, 'proveedores', escribir=True)
    return Response(s.asociar_beneficiario_ce(request.user, pk, request.data))
