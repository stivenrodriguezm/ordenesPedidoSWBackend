"""Conjunto de la lista de precios en la venta (2026-10-24): siempre entra por piezas, cada
una con su proveedor (un pedido a cada uno) y su precio dentro del conjunto; los costos
propios del conjunto (su Transporte…) van en una línea aparte. El total es el de la lista."""
from decimal import Decimal

from listaprecios.models import CargoVariante, ComponenteJuego, LineaProducto, VarianteProducto
from listaprecios.services import calcular_precio
from ordenes.models import LineaVenta, OrdenPedido, RolePermission
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase


class ConjuntoPorPiezasTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        RolePermission.objects.filter(role='administrador').delete()  # sin configuración = acceso total
        cat = self.variante.categoria
        self.mesa = VarianteProducto.objects.create(linea=LineaProducto.objects.create(nombre='Tapa', slug='tapa'), categoria=cat, nombre='Tapa', costo_base=50)
        self.base_mesa = VarianteProducto.objects.create(linea=LineaProducto.objects.create(nombre='Base', slug='base'), categoria=cat, nombre='Base', costo_base=30)
        self.juego = VarianteProducto.objects.create(linea=self.variante.linea, categoria=cat, nombre='Comedor', costo_base=0)
        CargoVariante.objects.create(variante=self.juego, descripcion='Transporte', valor=60, tipo=CargoVariante.TIPO_TRANSPORTE)
        self.c_mesa = ComponenteJuego.objects.create(juego=self.juego, variante=self.mesa, cantidad=1)
        self.c_base = ComponenteJuego.objects.create(juego=self.juego, variante=self.base_mesa, cantidad=1, orden=1)
        self.c_sillas = ComponenteJuego.objects.create(juego=self.juego, variante=self.variante, cantidad=2, orden=2)
        self.ref_mesa = self.referencia(self.proveedor('Proveedor de tapas'), 'Tapa ficticia')
        self.ref_base = self.referencia(self.proveedor('Proveedor de bases'), 'Base ficticia')

    def piezas(self, conjunto_cantidad=1, **costos):
        conj = dict(conjunto='c-val', conjunto_nombre='Comedor Valencia', conjunto_cantidad=conjunto_cantidad)
        sin_tela = dict(grupo_catalogo=None, opcionales=[], tela_modo='no_aplica', texto_cliente='')
        return [
            self.fila(variante=self.mesa.pk, juego=self.juego.pk, pieza=self.c_mesa.pk, referencia=self.ref_mesa.pk, cantidad=conjunto_cantidad, **sin_tela, **conj),
            self.fila(variante=self.base_mesa.pk, juego=self.juego.pk, pieza=self.c_base.pk, referencia=self.ref_base.pk, cantidad=conjunto_cantidad, **sin_tela, **conj),
            self.fila(juego=self.juego.pk, pieza=self.c_sillas.pk, opcionales=[], texto_cliente='', cantidad=2 * conjunto_cantidad, **conj),
            {'tipo': 'transporte', 'juego': self.juego.pk, 'producto_nombre': 'Transporte', 'cantidad': 1,
             'precio_lista_override': costos.get('valor', '1'), 'tela_modo': 'no_aplica', 'sin_texto_proveedor': True, **conj},
        ]

    def test_el_catalogo_divide_el_conjunto_aunque_tenga_costos_propios(self):
        r = self.api_asesor.get('/api/productos-venta/catalogo/', {'id': self.juego.pk})
        p = r.data['results'][0]
        self.assertEqual([(x['pieza'], x['variante'], x['cantidad']) for x in p['piezas']],
                         [(self.c_mesa.pk, self.mesa.pk, 1), (self.c_base.pk, self.base_mesa.pk, 1), (self.c_sillas.pk, self.variante.pk, 2)])
        # Su Transporte (60 × multiplicador 2) va aparte, como transporte del conjunto.
        self.assertEqual((p['costos_conjunto'], p['costos_conjunto_nombre'], p['costos_conjunto_tipo']), ('120.00', 'Transporte', 'transporte'))

    def test_total_igual_a_la_lista_y_un_pedido_por_proveedor(self):
        d = self.guardar(self.piezas())
        esperado = calcular_precio(self.juego, self.grupo, [])
        self.assertEqual(Decimal(d['valor_lista']), esperado)
        costos = LineaVenta.objects.get(tipo='transporte')
        # El valor lo pone la lista de precios, no el que llegue del navegador.
        self.assertEqual((costos.precio_lista_unitario, costos.conjunto), (Decimal(120), 'c-val'))
        self.assertTrue(all(l['texto_cliente'] == '' for l in d['lineas'] if l['tipo'] == 'producto'))  # nada se autocompleta
        piezas = [l for l in d['lineas'] if l['tipo'] == 'producto']
        self.assertEqual({(l['juego'], l['pieza']) for l in piezas}, {(self.juego.pk, c.pk) for c in (self.c_mesa, self.c_base, self.c_sillas)})
        r = self.api_asesor.post(self.url + 'pedidos/', {'revision': d['revision'], 'fecha_esperada': '2026-10-20',
                                                       'lineas': [{'linea': l['id'], 'cantidad': l['cantidad']} for l in piezas]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data['ordenes']), 3)
        self.assertEqual(set(OrdenPedido.objects.filter(venta=self.v).values_list('proveedor_id', flat=True)),
                         {self.prov.pk, self.ref_mesa.proveedor_id, self.ref_base.proveedor_id})

    def test_dos_conjuntos_duplican_sus_costos(self):
        d = self.guardar(self.piezas(conjunto_cantidad=2, valor='999'))
        self.assertEqual(Decimal(d['valor_lista']), calcular_precio(self.juego, self.grupo, []) * 2)
        self.assertEqual(LineaVenta.objects.get(tipo='transporte').precio_lista_unitario, Decimal(240))

    def test_una_pieza_de_otro_conjunto_se_rechaza(self):
        filas = self.piezas()
        filas[0]['pieza'] = self.c_base.pk
        r = self.api_asesor.post(self.url, {'revision': 0, 'lineas': filas, 'confirmar': True, 'distribuir_total': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('no corresponde', str(r.data))
