"""Identidad explícita de beneficiarios y preparación desde comprobantes."""
import hashlib
import json
from django.db.models import Exists, OuterRef, Q, Subquery, Value, CharField
from django.db.models.functions import Coalesce
from .models import CuentaBancaria, DetallePago
from .catalogo import BANCOS


def nombre_ce(ce):
    if ce.proveedor_id:
        return ce.proveedor.nombre_empresa
    if ce.proveedor_tela_id:
        return ce.proveedor_tela.nombre_empresa
    return ce.proveedor_otro_nombre or 'Sin beneficiario asociado'


def titular_ce(ce):
    if ce.proveedor_id:
        return {'proveedor': ce.proveedor_id}
    if ce.proveedor_tela_id:
        return {'proveedor_tela': ce.proveedor_tela_id}
    return None


def pertenece(c, ce):
    return bool(c and ((ce.proveedor_id and c.proveedor_id == ce.proveedor_id) or
                      (ce.proveedor_tela_id and c.proveedor_tela_id == ce.proveedor_tela_id)))


def cuentas_ce(ce):
    propietario = ce.proveedor if ce.proveedor_id else ce.proveedor_tela if ce.proveedor_tela_id else None
    return list(propietario.cuentas_bancarias.all()) if propietario else []


def elegida_ce(ce, cuentas):
    if ce.cuenta_destino_id:
        return next((c for c in cuentas if c.id == ce.cuenta_destino_id and c.activa), None)
    activas = [c for c in cuentas if c.activa]
    principales = [c for c in activas if c.principal]
    return principales[0] if len(principales) == 1 else activas[0] if len(activas) == 1 else None


def huella_ce(ce):
    # Incluye productos, facturas y conceptos que se muestran durante la revisión.
    from ordenes.serializers import ComprobanteEgresoSerializer
    datos = {k: getattr(ce, k) for k in ('id', 'proveedor_id', 'proveedor_tela_id', 'estado', 'medio_pago', 'cuenta_destino_id', 'concepto', 'descripcion', 'otros_conceptos', 'proveedor_otro_nombre', 'fecha', 'recibido_por')}
    datos['valor'] = str(ce.valor)
    datos['facturas'] = ComprobanteEgresoSerializer().get_facturas_detalle(ce)
    datos['cuentas'] = [{k: getattr(c, k) for k in ('id', 'revision', 'activa', 'principal')} for c in cuentas_ce(ce)]
    return hashlib.sha256(json.dumps(datos, sort_keys=True, default=str).encode()).hexdigest()


def informacion_ce(ce):
    cuentas = cuentas_ce(ce)
    elegida = elegida_ce(ce, cuentas)
    grupo = getattr(ce, 'archivo_bancario_id', None)
    if not hasattr(ce, 'archivo_bancario_id'):
        grupo = ce.pagos_bancarios.filter(incluido=True, rechazado=False).exclude(lote__estado='anulado').values_list('lote_id', flat=True).first()
    disponible = ce.medio_pago == 'Transferencia' and ce.estado == 'Por Confirmar Pago' and bool(titular_ce(ce)) and not grupo
    return {'titular': titular_ce(ce), 'disponible': disponible, 'archivo': grupo,
            'cuenta': elegida.id if elegida else None, 'banco': elegida.banco if elegida else '',
            'banco_nombre': BANCOS.get(elegida.banco, '') if elegida else '',
            'huella': huella_ce(ce) if ce.estado == 'Por Confirmar Pago' and ce.medio_pago == 'Transferencia' and not grupo else None,
            'cuentas': [{'id': c.id, 'banco': c.banco, 'banco_nombre': BANCOS.get(c.banco, c.banco),
                         'tipo': c.tipo, 'numero': c.numero, 'alias': c.alias, 'activa': c.activa,
                         'nombres': c.nombres, 'apellidos': c.apellidos, 'documento': c.documento, 'tipo_documento': c.tipo_documento} for c in cuentas]}


def preparar_consulta(qs, params):
    reservados = DetallePago.objects.filter(comprobante_id=OuterRef('pk'), incluido=True, rechazado=False).exclude(lote__estado='anulado').order_by('id')
    qs = qs.select_related('proveedor_tela', 'cuenta_destino').prefetch_related('proveedor__cuentas_bancarias', 'proveedor_tela__cuentas_bancarias').annotate(
        archivo_bancario_id=Subquery(reservados.values('lote_id')[:1]))
    if params.get('solo_pagables') == '1':
        qs = qs.filter(medio_pago='Transferencia', estado='Por Confirmar Pago', archivo_bancario_id__isnull=True).filter(Q(proveedor__isnull=False) | Q(proveedor_tela__isnull=False))
    banco = params.get('banco_destino')
    if banco:
        # Una principal, o una única cuenta activa: la misma sugerencia que ve el vendedor.
        propietario = Q(proveedor_id=OuterRef('proveedor_id'), proveedor_id__isnull=False) | Q(proveedor_tela_id=OuterRef('proveedor_tela_id'), proveedor_tela_id__isnull=False)
        activas = CuentaBancaria.objects.filter(propietario, activa=True)
        principal = activas.filter(principal=True).order_by('id')
        otra = activas.order_by('id')
        varias = activas.order_by('id')[1:2]
        qs = qs.annotate(_varias_cuentas=Exists(varias), _principal_banco=Subquery(principal.values('banco')[:1]), _unica_banco=Subquery(otra.values('banco')[:1]))
        from django.db.models import Case, When
        qs = qs.annotate(_banco_pago=Case(
            When(cuenta_destino__activa=True, then='cuenta_destino__banco'),
            When(cuenta_destino__isnull=False, then=Value('')),
            When(_principal_banco__isnull=False, then='_principal_banco'),
            When(_varias_cuentas=False, then=Coalesce('_unica_banco', Value(''))),
            default=Value(''), output_field=CharField()))
        qs = qs.filter(_banco_pago='' if banco == 'sin_cuenta' else banco)
    return qs
