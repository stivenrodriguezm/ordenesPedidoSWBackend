"""Regresiones de recibos de caja (H03, H09, H15 · P03-01, P03-04 · anexo A)."""
from decimal import Decimal

from ordenes.models import Caja, PagoReciboCaja, ReciboCaja
from ordenes.tests.utils import LottusTestCase


class ConfirmacionPagoTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.dueno = self.crear_usuario('owner', role='vendedor')
        self.v = self.venta(self.dueno)
        self.rc = ReciboCaja.objects.create(id=9900, venta=self.v)
        self.pago = PagoReciboCaja.objects.create(recibo=self.rc, metodo_pago='Davivienda', valor='50', estado='Pendiente')

    def test_transfer_changed_to_cash_missing_cash_movement(self):
        c = self.api(self.admin)
        r1 = c.put('/api/recibos-caja/9900/editar/', {
            'pagos_pendientes': [{'id': self.pago.pk, 'metodo_pago': 'Efectivo', 'valor': '50'}],
        }, format='json')
        self.assertEqual(r1.status_code, 200, r1.data)
        r2 = c.patch(f'/api/recibos-caja/pagos/{self.pago.pk}/confirmar/', {}, format='json')
        self.assertIn(r2.status_code, (200, 400))
        self.v.refresh_from_db(); self.pago.refresh_from_db()
        # Exactamente un abono y un movimiento de caja, sin importar el camino.
        self.assertEqual(self.v.abono, Decimal('50'))
        self.assertEqual(self.v.saldo, Decimal('950'))
        self.assertEqual(self.pago.estado, 'Confirmado')
        self.assertEqual(Caja.objects.filter(tipo='ingreso').count(), 1)
        self.assertEqual(self.saldo_caja(), Decimal('50'))

    def test_doble_confirmacion_abona_una_vez(self):
        c = self.api(self.admin)
        self.assertEqual(c.patch(f'/api/recibos-caja/pagos/{self.pago.pk}/confirmar/', {}, format='json').status_code, 200)
        self.assertEqual(c.patch(f'/api/recibos-caja/pagos/{self.pago.pk}/confirmar/', {}, format='json').status_code, 200)
        self.v.refresh_from_db()
        self.assertEqual(self.v.abono, Decimal('50'))
        self.assertEqual(Caja.objects.count(), 0)  # transferencia no toca caja

    def test_confirmar_efectivo_pendiente_crea_movimiento(self):
        """Un pago en efectivo pendiente (datos heredados) se confirma con su ingreso de caja."""
        p = PagoReciboCaja.objects.create(recibo=self.rc, metodo_pago='Efectivo', valor='30', estado='Pendiente')
        r = self.api(self.admin).patch(f'/api/recibos-caja/pagos/{p.pk}/confirmar/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.saldo_caja(), Decimal('30'))
        self.v.refresh_from_db()
        self.assertEqual(self.v.abono, Decimal('30'))


class CrearReciboTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.v = self.venta(self.crear_usuario('owner'))

    def test_recibo_efectivo_aplica_abono_y_caja(self):
        r = self.api(self.admin).post('/api/recibos-caja/crear/', {
            'id': 501, 'venta': self.v.id, 'pagos': [{'metodo_pago': 'Efectivo', 'valor': '100'}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.v.refresh_from_db()
        self.assertEqual(self.v.abono, Decimal('100'))
        self.assertEqual(self.saldo_caja(), Decimal('100'))

    def test_fallo_en_segunda_linea_no_deja_nada(self):
        r = self.api(self.admin).post('/api/recibos-caja/crear/', {
            'id': 502, 'venta': self.v.id,
            'pagos': [{'metodo_pago': 'Efectivo', 'valor': '100'}, {'metodo_pago': 'Inventado', 'valor': '5'}],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ReciboCaja.objects.filter(id=502).exists())
        self.v.refresh_from_db()
        self.assertEqual(self.v.abono, Decimal('0'))
        self.assertEqual(Caja.objects.count(), 0)

    def test_editar_recibo_invalido_no_guarda_cabecera(self):
        rc = ReciboCaja.objects.create(id=503, venta=self.v, nota='original')
        PagoReciboCaja.objects.create(recibo=rc, metodo_pago='Davivienda', valor='10')
        r = self.api(self.admin).put('/api/recibos-caja/503/editar/', {
            'nota': 'cambiada', 'pagos_pendientes': [{'metodo_pago': 'Inventado', 'valor': '5'}],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        rc.refresh_from_db()
        self.assertEqual(rc.nota, 'original')
        self.assertEqual(rc.pagos.count(), 1)

    def test_recibo_de_venta_ajena_para_vendedor(self):
        vendedor = self.crear_usuario('seller')
        self.permisos('vendedor', ['CREAR_RECIBO'])
        r = self.api(vendedor).post('/api/recibos-caja/crear/', {
            'id': 504, 'venta': self.v.id, 'pagos': [{'metodo_pago': 'Davivienda', 'valor': '10'}],
        }, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(ReciboCaja.objects.filter(id=504).exists())

class TotalesRecibosTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.dueno = self.crear_usuario('owner', role='vendedor')
        self.v = self.venta(self.dueno)
        self.rc = ReciboCaja.objects.create(id=9901, venta=self.v)
        PagoReciboCaja.objects.create(recibo=self.rc, metodo_pago='Efectivo', valor='50', estado='Confirmado')
        PagoReciboCaja.objects.create(recibo=self.rc, metodo_pago='Davivienda', valor='70', estado='Pendiente')

    def test_total_filtrado_suma_pagos_del_conjunto(self):
        c = self.api(self.admin)
        r = c.get('/api/recibos-caja/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['valor'])), Decimal('120'))
        # Con filtro de medio, el total es el de los pagos de ese medio.
        r = c.get('/api/recibos-caja/', {'medio_pago': 'Efectivo'})
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['valor'])), Decimal('50'))
