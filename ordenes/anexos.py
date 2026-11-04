"""Anexos diligenciados en papel: registrar existencia sin editar la venta."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Venta
from .permissions import check_feature_permission, ventas_visibles
from .servicios import auditar


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
    return Response(registrar_anexo(venta, request.user))
