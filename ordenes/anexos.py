"""Anexos diligenciados en papel: registrar existencia sin editar la venta."""
import base64

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Venta
from .permissions import check_feature_permission, ventas_visibles
from .servicios import auditar, idempotente
from .anexos_pdf import generar_anexo_pdf
from impresion.views import LimiteTrabajos
from lottusPedidos.throttling import ApiUserRateThrottle


@transaction.atomic
def registrar_anexo(venta, usuario):
    # La actualización condicional evita duplicar la auditoría en reintentos.
    if Venta.objects.filter(pk=venta.pk, tiene_anexo=False).update(tiene_anexo=True):
        auditar(usuario, 'venta.anexo_registrado', venta, {'tiene_anexo': True})
    return {'id': venta.pk, 'tiene_anexo': True}


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def agregar_anexo(request, venta_id):
    venta = get_object_or_404(ventas_visibles(request).only('id'), pk=venta_id)
    pdf = generar_anexo_pdf(venta.pk)
    return Response({**registrar_anexo(venta, request.user), 'pdf': base64.b64encode(pdf).decode('ascii')})


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
@throttle_classes([ApiUserRateThrottle, LimiteTrabajos])
@idempotente('venta.anexo.imprimir')
def imprimir_anexo(request, venta_id):
    from impresion import servicios as impresion
    from impresion.models import Impresora, TrabajoImpresion
    from impresion.views import _trabajo

    venta = get_object_or_404(ventas_visibles(request).only('id'), pk=venta_id)
    pk = request.data.get('impresora')
    impresora = Impresora.objects.filter(pk=pk if str(pk).isdigit() else None, activa=True).first()
    if impresora is None:
        return Response({'error': 'La impresora no está disponible.'}, status=400)
    if not impresion.admite_anexos(impresora.pk):
        return Response({'error': 'Actualiza el agente de la impresora para imprimir anexos en PDF a doble cara. También puedes imprimir desde esta computadora.'}, status=409)
    pdf = base64.b64encode(generar_anexo_pdf(venta.pk, copias=1)).decode('ascii')
    with transaction.atomic():
        registrar_anexo(venta, request.user)
        trabajo = TrabajoImpresion.objects.create(
            impresora=impresora, usuario=request.user, titulo=f'Anexo a compra No. {venta.pk}',
            html='', pdf=pdf, copias=2, doble_cara=True,
        )
        transaction.on_commit(lambda: impresion.avisar(impresora.pk))
    return Response({**_trabajo(trabajo), 'en_linea': impresion.en_linea(impresora.pk)}, status=201)
