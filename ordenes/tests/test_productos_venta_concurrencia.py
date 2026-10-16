import unittest
from datetime import date

from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from ordenes.models import Cliente, CustomUser, DetallePedido, LineaVenta, OrdenPedido, Proveedor, Referencia, Venta
from ordenes.tests.test_concurrencia import en_paralelo


@unittest.skipUnless(connection.vendor == 'mysql', 'Requiere MySQL aislado')
class ProductosVentaConcurrenciaTests(TransactionTestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create(username='admin-productos', role='administrador')
        cliente = Cliente.objects.create(nombre='Ficticio', cedula='p15', telefono1='0')
        self.venta = Venta.objects.create(id=123, cliente=cliente, vendedor=self.admin, valor_total=100,
            saldo=100, fecha_entrega=date.today(), revision_productos=1, productos_confirmados=True, valor_lista=100)
        proveedor = Proveedor.objects.create(nombre_empresa='Fábrica P15')
        ref = Referencia.objects.create(proveedor=proveedor, nombre='Silla')
        self.linea = LineaVenta.objects.create(venta=self.venta, producto_nombre='Silla', cantidad=1, precio_unitario=100,
            precio_lista_unitario=100, subtotal=100, referencia=ref)

    def cliente_api(self):
        c = APIClient(); c.force_authenticate(self.admin)
        return c

    def test_dos_pedidos_solo_comprometen_una_unidad(self):
        body = {'revision': 1, 'fecha_esperada': str(date.today()), 'lineas': [{'linea': self.linea.pk, 'cantidad': 1}]}
        codigos = en_paralelo(2, lambda i: self.cliente_api().post(f'/api/ventas/{self.venta.pk}/productos/pedidos/', body, format='json').status_code)
        self.assertEqual(sorted(codigos), [201, 409])
        self.assertEqual(DetallePedido.objects.count(), 1)
        self.assertEqual(OrdenPedido.objects.count(), 1)

    def test_dos_guardados_misma_revision_solo_uno_gana(self):
        body = {'revision': 1, 'confirmar': True, 'lineas': [{'id': self.linea.pk, 'producto_nombre': 'Silla',
            'referencia': self.linea.referencia_id, 'cantidad': 1, 'precio_lista_override': '100', 'motivo_precio': 'Especial',
            'texto_proveedor': 'Silla roble', 'texto_cliente': 'Silla', 'tela_modo': 'no_aplica'}]}
        codigos = en_paralelo(2, lambda i: self.cliente_api().post(f'/api/ventas/{self.venta.pk}/productos/', body, format='json').status_code)
        self.assertEqual(sorted(codigos), [200, 409])
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.revision_productos, 2)
