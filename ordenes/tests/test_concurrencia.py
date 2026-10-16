"""Carreras reales con conexiones independientes (H15 · P03-06, P04-03).

Solo corren con settings_test_mysql (MySQL desechable): SQLite serializa las
escrituras y no valida bloqueos de fila. Se sincronizan con una barrera, no
con pausas arbitrarias."""
import threading
import unittest
from datetime import date
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from ordenes.models import Caja, Cliente, ComprobanteEgreso, CuentaCaja, CustomUser, PagoReciboCaja, Proveedor, ReciboCaja, Venta
from suministros.models import FacturaProveedor, Inventario, RemisionSuministro


def en_paralelo(n, funcion):
    barrera = threading.Barrier(n)
    resultados = [None] * n

    def correr(i):
        try:
            barrera.wait()
            resultados[i] = funcion(i)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resultados


@unittest.skipUnless(connection.vendor == 'mysql', 'Requiere MySQL aislado (settings_test_mysql)')
class CarrerasMySQLTests(TransactionTestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create(username='admin', role='administrador')

    def cliente_api(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c

    def test_confirmacion_simultanea_abona_una_vez(self):
        cliente = Cliente.objects.create(nombre='C', cedula='c1', telefono1='0')
        venta = Venta.objects.create(id=1, cliente=cliente, vendedor=self.admin, valor_total=100, saldo=100,
                                     fecha_venta=date.today(), fecha_entrega=date.today())
        rc = ReciboCaja.objects.create(id=1, venta=venta)
        pago = PagoReciboCaja.objects.create(recibo=rc, metodo_pago='Efectivo', valor=50)
        en_paralelo(4, lambda i: self.cliente_api().patch(f'/api/recibos-caja/pagos/{pago.pk}/confirmar/').status_code)
        venta.refresh_from_db()
        self.assertEqual(venta.abono, Decimal('50'))
        self.assertEqual(Caja.objects.filter(tipo='ingreso').count(), 1)

    def test_egresos_simultaneos_con_caja_vacia(self):
        p = Proveedor.objects.create(nombre_empresa='P')
        self.cliente_api().post('/api/caja/', {'tipo': 'ingreso', 'valor': '100', 'concepto': 'base'}, format='json')
        codigos = en_paralelo(3, lambda i: self.cliente_api().post('/api/comprobantes-egreso/crear/', {
            'proveedor': p.id, 'recibido_por': 'F', 'valor': '60', 'medio_pago': 'Efectivo'}, format='json').status_code)
        self.assertEqual(sorted(codigos), [201, 400, 400])
        self.assertGreaterEqual(min(Caja.objects.values_list('total_acumulado', flat=True)), 0)

    def test_numeracion_simultanea_sin_duplicados(self):
        p = Proveedor.objects.create(nombre_empresa='P')
        en_paralelo(5, lambda i: self.cliente_api().post('/api/comprobantes-egreso/crear/', {
            'proveedor': p.id, 'recibido_por': 'F', 'valor': '10', 'medio_pago': 'Transferencia'}, format='json').status_code)
        ids = list(ComprobanteEgreso.objects.values_list('id', flat=True))
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)

    def test_reserva_simultanea_de_una_unidad(self):
        item = Inventario.objects.create(id_referencia='RACE1', disponibilidad='exhibicion')
        en_paralelo(3, lambda i: self.cliente_api().post('/api/suministros/remisiones/', {
            'fecha_entrega': str(date.today()), 'inventario_items': [item.pk]}, format='json').status_code)
        activas = RemisionSuministro.objects.filter(inventario_items=item, estado__in=['creada', 'despachada']).count()
        self.assertEqual(activas, 1)

    def test_facturas_simultaneas_no_reciben_de_mas_una_linea(self):
        """P11-01: línea de 3; dos facturas de 2 a la vez: solo cabe una."""
        from ordenes.models import DetallePedido, OrdenPedido, Referencia
        prov = Proveedor.objects.create(nombre_empresa='Proveedor ficticio recepción')
        ref = Referencia.objects.create(proveedor=prov, nombre='Ref ficticia')
        orden = OrdenPedido.objects.create(proveedor=prov, usuario=self.admin, fecha_esperada=date.today())
        linea = DetallePedido.objects.create(orden=orden, referencia=ref, cantidad=3, especificaciones='-')
        codigos = en_paralelo(2, lambda i: self.cliente_api().post('/api/suministros/facturas/', {
            'id_manual': f'REC-{i}', 'proveedor': prov.id, 'valor': '20',
            'productos': [{'referencia': ref.id, 'costo': '10', 'cantidad': 2, 'detalle_pedido': linea.id}]},
            format='json').status_code)
        self.assertEqual(sorted(codigos), [201, 400])
        self.assertEqual(Inventario.objects.filter(detalle_pedido=linea).count(), 2)

    def test_confirmaciones_simultaneas_de_una_entrega(self):
        """P11-03: dos personas confirman la misma remisión a la vez: un solo cierre."""
        from suministros.models import NovedadEntrega, RemisionEvento
        items = [Inventario.objects.create(id_referencia=f'ENT{i}', disponibilidad='exhibicion') for i in range(2)]
        rem = RemisionSuministro.objects.create(fecha_entrega=date.today(), estado='despachada')
        rem.inventario_items.set(items)
        Inventario.objects.filter(pk__in=['ENT0', 'ENT1']).update(disponibilidad='despachado')
        en_paralelo(2, lambda i: self.cliente_api().patch(f'/api/suministros/remisiones/{rem.id}/', {
            'estado': 'finalizada', 'no_entregados': [{'inventario': 'ENT1', 'motivo': 'faltante'}]},
            format='json').status_code)
        self.assertEqual(RemisionEvento.objects.filter(remision=rem, tipo='finalizada').count(), 1)
        self.assertEqual(NovedadEntrega.objects.filter(remision=rem).count(), 1)
        self.assertEqual(Inventario.objects.get(pk='ENT1').disponibilidad, 'exhibicion')
