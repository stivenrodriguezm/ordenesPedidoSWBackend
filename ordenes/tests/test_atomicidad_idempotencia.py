"""Fallos a mitad de operaciones financieras e idempotencia (H03, H15 · P03-01,
P03-06). Comparan el estado completo antes y después."""
from decimal import Decimal

from ordenes.models import Caja, Cliente, ComprobanteEgreso, RegistroAuditoria, Venta
from ordenes.tests.utils import LottusTestCase
from suministros.models import FacturaProveedor, Inventario


def foto(*objs):
    estado = []
    for o in objs:
        o.refresh_from_db()
        estado.append({f.attname: getattr(o, f.attname) for f in o._meta.concrete_fields})
    return estado


class EdicionEgresoAtomicaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.p1 = self.proveedor()
        self.ce = ComprobanteEgreso.objects.create(id=3500, proveedor=self.p1, valor='100', medio_pago='Transferencia',
                                                   estado='Por Confirmar Pago', recibido_por='Ficticio')
        self.f = FacturaProveedor.objects.create(id_manual='fx', proveedor=self.p1, valor='100',
                                                 estado='pago_en_proceso', comprobante_egreso=self.ce)

    def test_pagar_en_efectivo_sin_saldo_no_deja_cambios(self):
        antes = foto(self.ce, self.f)
        r = self.api(self.admin).put('/api/comprobantes-egreso/3500/editar/', {
            'proveedor': self.p1.id, 'recibido_por': 'Otra', 'valor': '100', 'medio_pago': 'Efectivo',
            'estado': 'Pagado', 'facturas_ids': [self.f.id],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(foto(self.ce, self.f), antes)
        self.assertEqual(Caja.objects.count(), 0)
        self.assertFalse(RegistroAuditoria.objects.filter(accion='egreso.editar').exists())

    def test_revertir_pago_efectivo_compensa_y_referencia(self):
        c = self.api(self.admin)
        c.post('/api/caja/', {'tipo': 'ingreso', 'valor': '500', 'concepto': 'base'}, format='json')
        r = c.put('/api/comprobantes-egreso/3500/editar/', {
            'proveedor': self.p1.id, 'recibido_por': 'X', 'valor': '100', 'medio_pago': 'Efectivo',
            'estado': 'Pagado', 'facturas_ids': [self.f.id]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.saldo_caja(), Decimal('400'))
        r = c.put('/api/comprobantes-egreso/3500/editar/', {
            'proveedor': self.p1.id, 'recibido_por': 'X', 'valor': '100', 'medio_pago': 'Efectivo',
            'estado': 'Por Confirmar Pago', 'facturas_ids': [self.f.id]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.saldo_caja(), Decimal('500'))
        reversa = Caja.objects.get(tipo='ingreso', comprobante_egreso=self.ce)
        self.assertIsNotNone(reversa.reversa_de_id)
        self.assertEqual(reversa.reversa_de.tipo, 'egreso')


class IdempotenciaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')

    def test_reintento_con_misma_clave_no_duplica(self):
        c = self.api(self.admin)
        cuerpo = {'tipo': 'ingreso', 'valor': '100', 'concepto': 'x'}
        r1 = c.post('/api/caja/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='k-1')
        r2 = c.post('/api/caja/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='k-1')
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(Caja.objects.count(), 1)
        self.assertEqual(self.saldo_caja(), Decimal('100'))

    def test_misma_clave_otro_contenido_es_conflicto(self):
        c = self.api(self.admin)
        c.post('/api/caja/', {'tipo': 'ingreso', 'valor': '100', 'concepto': 'x'}, format='json', HTTP_IDEMPOTENCY_KEY='k-2')
        r = c.post('/api/caja/', {'tipo': 'ingreso', 'valor': '999', 'concepto': 'x'}, format='json', HTTP_IDEMPOTENCY_KEY='k-2')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Caja.objects.count(), 1)

    def test_venta_reintentada_no_duplica(self):
        c = self.api(self.admin)
        cuerpo = {
            'cliente_nuevo': True,
            'cliente': {'nombre': 'Ana Prueba', 'cedula': '9990001', 'telefono1': '3001234567'},
            'venta': {'id': 990001, 'id_vendedor': self.admin.id, 'valor_total': '1000',
                      'fecha_venta': '2026-10-02', 'fecha_entrega': '2026-10-05', 'sede': 'Lottus 1'},
        }
        r1 = c.post('/api/ventas/crear/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='v-1')
        r2 = c.post('/api/ventas/crear/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='v-1')
        self.assertEqual((r1.status_code, r2.status_code), (201, 201), (r1.data, r2.data))
        self.assertEqual(r1.data['venta_id'], r2.data['venta_id'])
        self.assertEqual(Venta.objects.count(), 1)
        self.assertEqual(Cliente.objects.filter(cedula='9990001').count(), 1)

    def test_factura_reintentada_no_duplica_inventario(self):
        p = self.proveedor()
        ref = self.referencia(p)
        cuerpo = {'id_manual': 'idem-f1', 'proveedor': p.pk, 'valor': '20',
                  'productos': [{'referencia': ref.pk, 'costo': '10', 'cantidad': 2}]}
        c = self.api(self.admin)
        r1 = c.post('/api/suministros/facturas/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='f-1')
        r2 = c.post('/api/suministros/facturas/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='f-1')
        self.assertEqual((r1.status_code, r2.status_code), (201, 201), (r1.data, r2.data))
        self.assertEqual(FacturaProveedor.objects.filter(id_manual='idem-f1').count(), 1)
        self.assertEqual(Inventario.objects.filter(factura__id_manual='idem-f1').count(), 2)

    def test_egreso_reintentado_no_duplica_numero_ni_pago(self):
        p = self.proveedor()
        cuerpo = {'proveedor': p.id, 'recibido_por': 'F', 'valor': '10', 'medio_pago': 'Transferencia'}
        c = self.api(self.admin)
        r1 = c.post('/api/comprobantes-egreso/crear/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='e-1')
        r2 = c.post('/api/comprobantes-egreso/crear/', cuerpo, format='json', HTTP_IDEMPOTENCY_KEY='e-1')
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(ComprobanteEgreso.objects.count(), 1)


class CorsIdempotenciaTests(LottusTestCase):
    def test_navegador_puede_enviar_idempotency_key(self):
        r = self.client.options('/api/caja/', HTTP_ORIGIN='https://app.muebleslottus.com',
                                HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
                                HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization,content-type,idempotency-key')
        self.assertIn('idempotency-key', r.get('access-control-allow-headers', '').lower())
