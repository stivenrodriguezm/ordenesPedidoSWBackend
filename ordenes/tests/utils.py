"""Datos ficticios y utilidades compartidas por las regresiones de la auditoría
2026-10-02 (anexo A del plan). Todo se crea dentro de la base de pruebas; nada
proviene de datos reales."""
from decimal import Decimal
import socket

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ordenes.models import (
    Caja, Cliente, CustomUser, Proveedor, Referencia, RolePermission, Venta,
)


def _sin_red(*args, **kwargs):
    raise RuntimeError('Red externa deshabilitada durante las pruebas')


class LottusTestCase(TestCase):
    """Base: bloquea conexiones de red y ofrece fábricas mínimas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._connect_original = socket.socket.connect
        socket.socket.connect = _sin_red

    @classmethod
    def tearDownClass(cls):
        socket.socket.connect = cls._connect_original
        super().tearDownClass()

    _venta_seq = 100

    def crear_usuario(self, username, role='vendedor', **extra):
        return CustomUser.objects.create(username=username, first_name=extra.pop('first_name', username), role=role, **extra)

    def permisos(self, role, codigos):
        RolePermission.objects.update_or_create(role=role, defaults={'permissions': list(codigos)})

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def cliente(self, cedula='ficticio-001', nombre='Cliente ficticio'):
        return Cliente.objects.get_or_create(cedula=cedula, defaults={'nombre': nombre, 'telefono1': '000'})[0]

    def venta(self, vendedor, valor='1000', estado='pendiente', fecha=None, **extra):
        LottusTestCase._venta_seq += 1
        return Venta.objects.create(
            id=LottusTestCase._venta_seq, cliente=extra.pop('cliente', None) or self.cliente(),
            vendedor=vendedor, valor_total=Decimal(valor), saldo=Decimal(valor),
            fecha_venta=fecha or timezone.localdate(), fecha_entrega=timezone.localdate(), estado=estado, **extra,
        )

    def proveedor(self, nombre='Proveedor ficticio A'):
        return Proveedor.objects.get_or_create(nombre_empresa=nombre)[0]

    def referencia(self, proveedor, nombre='Referencia ficticia'):
        return Referencia.objects.create(proveedor=proveedor, nombre=nombre)

    def saldo_caja(self):
        ultimo = Caja.objects.order_by('-fecha_hora', '-id').first()
        return ultimo.total_acumulado if ultimo else Decimal('0')
