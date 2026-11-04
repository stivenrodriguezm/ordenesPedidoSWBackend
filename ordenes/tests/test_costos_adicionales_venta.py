from decimal import Decimal

from listaprecios.models import ComponenteJuego, Multiplicador, VarianteProducto
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase


class CostosAdicionalesVentaTests(LottusTestCase):
    setUp = base.ProductosVentaTests.setUp
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def calcular(self, fila, cliente=None):
        return (cliente or self.api_admin).post(self.url + 'calcular/', fila, format='json')

    def test_recargo_por_costo_multiplo_propio_cantidad_y_margen(self):
        self.variante.multiplicador = Multiplicador.objects.create(nombre='Propio', valor=3)
        self.variante.save()
        fila = self.fila(adicionales=[{'descripcion': 'Patas', 'costo': '30'}])
        r = self.calcular(fila)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['precio_lista_unitario'], '435.00')  # (115 + 30) × 3
        d = self.guardar([fila], cliente=self.api_admin)
        self.assertEqual(Decimal(d['valor_lista']), 870)  # dos unidades
        self.assertEqual(self.v.lineas.get().costo_estimado, 145)
        self.assertEqual(d['lineas'][0]['adicionales'], [{'descripcion': 'Patas', 'costo': '30.00'}])
        self.assertEqual(self.calcular(fila, self.api_asesor).status_code, 403)

    def test_precio_especial_por_costo_y_recargos_se_suman(self):
        fila = self.fila(costo_precio_especial='500', motivo_precio='Fabricación a medida',
                         adicionales=[{'descripcion': 'Instalación', 'costo': '30'}])
        d = self.guardar([fila], cliente=self.api_admin)
        self.assertEqual(Decimal(d['valor_lista']), 2120)  # (500 + 30) × 2 × 2 unidades
        self.assertEqual(self.v.lineas.get().costo_estimado, 530)
        self.assertEqual(d['lineas'][0]['costo_precio_especial'], '500')
        self.assertIsNone(d['lineas'][0]['precio_lista_override'])
        # Cambios de lista y edición de textos conservan la venta guardada.
        Multiplicador.objects.filter(es_general=True).update(valor=4)
        l = d['lineas'][0]
        l['texto_cliente'] = 'Otro texto'
        self.guardar([l], revision=d['revision'], cliente=self.api_admin)
        self.assertEqual(self.v.lineas.get().precio_lista_unitario, 1060)
        l['recalcular'] = True
        self.guardar([l], revision=d['revision'] + 1, cliente=self.api_admin)
        self.assertEqual(self.v.lineas.get().precio_lista_unitario, 2120)

    def test_pieza_usa_su_multiplo_exclusivo(self):
        juego = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Conjunto', costo_base=0)
        pieza = ComponenteJuego.objects.create(juego=juego, variante=self.variante, cantidad=1, multiplicador=4)
        fila = self.fila(juego=juego.pk, pieza=pieza.pk, adicionales=[{'descripcion': 'Patas', 'costo': '30'}])
        r = self.calcular(fila)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data['precio_lista_unitario']), 580)  # (115 + 30) × 4
        r = self.calcular({**fila, 'costo_precio_especial': '500', 'motivo_precio': 'A medida'})
        self.assertEqual(Decimal(r.data['precio_lista_unitario']), 2120)  # (500 + 30) × 4

    def test_transporte_general_producto_y_conservacion_historica(self):
        transporte = {'tipo': 'transporte', 'producto_nombre': 'Transporte', 'cantidad': 1, 'costo_servicio': '100'}
        r = self.calcular(transporte)
        self.assertEqual(r.data['precio_lista_unitario'], '200.00')
        propio = Multiplicador.objects.create(nombre='Transporte propio', valor='3.5')
        self.variante.multiplicador = propio
        self.variante.save()
        transporte['variante_multiplicador'] = self.variante.pk
        d = self.guardar([self.fila(), transporte], cliente=self.api_admin)
        l = next(l for l in d['lineas'] if l['tipo'] == 'transporte')
        self.assertEqual(l['precio_lista_unitario'], '350.00')
        self.assertEqual(l['costo_servicio'], '100')
        propio.valor = 4
        propio.save()
        d2 = self.guardar(d['lineas'], revision=d['revision'], cliente=self.api_admin)
        self.assertEqual(next(l for l in d2['lineas'] if l['tipo'] == 'transporte')['precio_lista_unitario'], '350.00')
        l['recalcular'] = True
        self.assertEqual(self.calcular(l).data['precio_lista_unitario'], '400.00')
        # El transporte histórico sigue siendo un valor de venta fijo.
        self.assertEqual(self.calcular({**transporte, 'costo_servicio': None, 'variante_multiplicador': None, 'precio_lista_override': '100'}).data['precio_lista_unitario'], '100.00')

    def test_transporte_con_multiplo_de_pieza(self):
        juego = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Juego', costo_base=0)
        pieza = ComponenteJuego.objects.create(juego=juego, variante=self.variante, cantidad=1, multiplicador=4)
        t = {'tipo': 'transporte', 'producto_nombre': 'Transporte', 'cantidad': 1, 'costo_servicio': '100',
             'variante_multiplicador': self.variante.pk, 'pieza_multiplicador': pieza.pk}
        self.assertEqual(self.calcular(t).data['precio_lista_unitario'], '400.00')
        self.assertEqual(self.calcular({**t, 'variante_multiplicador': None}).status_code, 400)

    def test_rechaza_centavos_y_contratos_mezclados_sin_guardar(self):
        for fila in (
            self.fila(adicionales=[{'descripcion': 'Patas', 'costo': '30.50'}]),
            self.fila(adicionales=[{'descripcion': 'Patas', 'costo': '30', 'importe_lista': '10'}]),
            self.fila(costo_precio_especial='100.50', motivo_precio='Especial'),
            self.fila(costo_precio_especial='100', precio_lista_override='200', motivo_precio='Especial'),
            self.fila(costo_precio_especial='100'),
            {'tipo': 'transporte', 'producto_nombre': 'Transporte', 'cantidad': 1, 'costo_servicio': '100.50'},
        ):
            self.assertEqual(self.calcular(fila).status_code, 400, fila)
        self.assertFalse(self.v.lineas.exists())
