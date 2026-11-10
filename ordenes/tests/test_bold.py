"""Bold (2026-11-04): cobro por datáfono que suma al precio de lista el 5 % de lo cobrado."""
from decimal import Decimal

from ordenes.models import LineaVenta
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase


class BoldTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        # Valor pactado suficiente para cubrir lo que suma Bold.
        type(self.v).objects.filter(pk=self.v.pk).update(valor_total=200000, saldo=200000)
        self.v.refresh_from_db()

    def bold(self, cobrado, **extra):
        return {'tipo': 'bold', 'producto_nombre': 'Bold', 'cantidad': 1, 'bold_cobrado': cobrado, **extra}

    def test_suma_el_cinco_por_ciento_exacto_sin_multiplicador(self):
        # El valor que mande el navegador no cuenta: lo calcula el servidor.
        d = self.guardar([self.fila(), self.bold('1000000', precio_lista_override='999')])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(460 + 50000))
        linea = next(l for l in d['lineas'] if l['tipo'] == 'bold')
        self.assertEqual((Decimal(linea['precio_lista_unitario']), Decimal(linea['bold_cobrado'])), (Decimal(50000), Decimal(1000000)))
        self.assertEqual(linea['por_pedir'], 0)
        guardada = self.v.lineas.get(tipo=LineaVenta.TIPO_BOLD)
        self.assertEqual(guardada.subtotal, Decimal(50000))
        self.assertEqual(sum(l.subtotal for l in self.v.lineas.all()), self.v.valor_total)
        # Al volver a guardar conserva lo cobrado y lo recalcula igual.
        d = self.guardar([self.fila(id=d['lineas'][0]['id']), self.bold('1234567', id=linea['id'])], revision=d['revision'])
        self.assertEqual(Decimal(next(l for l in d['lineas'] if l['tipo'] == 'bold')['precio_lista_unitario']), Decimal(61728))

    def test_exige_lo_cobrado_en_pesos_enteros(self):
        for cobrado in (None, '0', '1000000.50'):
            r = self.api_asesor.post(self.url, {'revision': self.api_asesor.get(self.url).data['revision'],
                                                'lineas': [self.fila(), self.bold(cobrado)]}, format='json')
            self.assertEqual(r.status_code, 400, cobrado)
            self.assertIn('bold_cobrado', r.data['lineas'][1], cobrado)
