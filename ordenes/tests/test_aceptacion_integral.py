"""P14: jornada financiera por API con permisos y tokens, datos ficticios.
Sin turnos de caja ni cuentas por pagar: módulos eliminados por decisión del
usuario (2026-10-06, D-ALCANCE)."""
from datetime import date
from decimal import Decimal
from rest_framework.test import APIClient
from ordenes.models import Caja, ComprobanteEgreso, PagoReciboCaja, ReciboCaja
from ordenes.servicios import cuenta_principal
from ordenes.tests.utils import LottusTestCase
from suministros.models import FacturaProveedor


class AceptacionIntegralTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin-aceptacion', role='administrador')
        self.cajero = self.crear_usuario('cajero-aceptacion', role='auxiliar')
        self.vendedor = self.crear_usuario('vendedor-aceptacion')
        self.permisos('auxiliar', ['VER_CAJA', 'CERRAR_CAJA', 'VER_RECIBOS', 'CREAR_RECIBO', 'CREAR_COMPROBANTE_EGRESO'])
        self.permisos('vendedor', ['VER_RECIBOS', 'VER_PROPIAS_VENTAS'])
        self.venta_ficticia = self.venta(self.vendedor, valor='1000')
        self.admin_api = self.api(self.admin)
        self.caja_api = self.api(self.cajero)
        self.factura = FacturaProveedor.objects.create(id_manual='ACEP-001', proveedor=self.proveedor(), valor='200', fecha_pago=date(2026, 12, 20))

    def test_jornada_cobro_mixto_reintento_pago_proveedor_y_cierre(self):
        payload = {'id': 14001, 'venta': self.venta_ficticia.pk, 'pagos': [
            {'metodo_pago': 'Efectivo', 'valor': '600'}, {'metodo_pago': 'Davivienda', 'valor': '400'}]}
        for _ in range(2):  # La respuesta original se perdió; reintento idéntico.
            r = self.caja_api.post('/api/recibos-caja/crear/', payload, format='json', HTTP_IDEMPOTENCY_KEY='acep-cobro-1')
            self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ReciboCaja.objects.count(), 1)
        self.assertEqual(cuenta_principal().saldo, Decimal('600'))
        transferencia = PagoReciboCaja.objects.get(metodo_pago='Davivienda')
        url = f'/api/recibos-caja/pagos/{transferencia.pk}/confirmar/'
        self.assertEqual(self.caja_api.patch(url).status_code, 403)
        for _ in range(2):
            self.assertEqual(self.admin_api.patch(url).status_code, 200)
        self.venta_ficticia.refresh_from_db()
        self.assertEqual((self.venta_ficticia.abono, self.venta_ficticia.saldo), (Decimal('1000'), Decimal('0')))
        # Pago completo de la factura con el comprobante de egreso de siempre.
        pago = {'id': 14002, 'proveedor': self.factura.proveedor_id, 'recibido_por': 'Proveedor ficticio', 'valor': '200',
                'medio_pago': 'Efectivo', 'estado': 'Pagado', 'facturas_ids': [self.factura.id]}
        for _ in range(2):
            r = self.admin_api.post('/api/comprobantes-egreso/crear/', pago, format='json', HTTP_IDEMPOTENCY_KEY='acep-proveedor-1')
            self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ComprobanteEgreso.objects.count(), 1)
        self.assertEqual(cuenta_principal().saldo, Decimal('400'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.fecha_pago, date(2026, 12, 20))  # la fecha límite no se pisa (D10f)
        self.assertIsNotNone(self.factura.fecha_pago_real)
        # Cierre de caja clásico: deja constancia sin cambiar el saldo.
        r = self.caja_api.post('/api/caja/cierre/', {'descuadre': 0}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(cuenta_principal().saldo, Decimal('400'))
        self.assertEqual(Caja.objects.filter(tipo='cierre').count(), 1)
        # Vendedor conserva acceso a su recibo y el administrador genera el reporte.
        r = self.api(self.vendedor).get('/api/recibos-caja/')
        self.assertEqual(r.data['results'][0]['estado'], 'Confirmado')
        self.assertEqual(self.admin_api.post('/api/reportes-operativos/recibos/exportar/').status_code, 200)

    def test_token_vigente_revalida_permisos_y_cuenta_desactivada(self):
        self.vendedor.set_password('clave-ficticia-solo-tests')
        self.vendedor.save()
        c = APIClient()
        login = c.post('/api/token/', {'username': self.vendedor.username, 'password': 'clave-ficticia-solo-tests'})
        self.assertEqual(login.status_code, 200, login.data)
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + login.data['access'])
        self.assertEqual(c.get('/api/recibos-caja/').status_code, 200)
        self.permisos('vendedor', [])
        self.assertEqual(c.get('/api/recibos-caja/').status_code, 403)
        self.vendedor.is_active = False
        self.vendedor.save()
        self.assertEqual(c.get('/api/recibos-caja/').status_code, 401)
        self.assertEqual(c.post('/api/token/refresh/', {'refresh': login.data['refresh']}).status_code, 401)
