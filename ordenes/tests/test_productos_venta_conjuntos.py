"""Productos de la venta (2026-10-15): remisión opcional, grupo y costo de la tela,
conjuntos (comedor = mesa + sillas) y costo sugerido para la factura del proveedor."""
from decimal import Decimal

from listaprecios.models import CargoVariante, ComponenteJuego, GrupoTela, LineaProducto, VarianteProducto
from ordenes.gestion_venta import texto_remision
from ordenes.models import LineaVenta, ProveedorTela
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase


class ConjuntosYFacturaTests(LottusTestCase):
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar
    pedir = base.ProductosVentaTests.pedir

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        self.permisos('administrador', ['ALL'])

    def test_sin_texto_para_el_cliente_la_remision_usa_el_nombre(self):
        d = self.guardar([self.fila(texto_cliente='')])
        linea = LineaVenta.objects.get(pk=d['lineas'][0]['id'])
        self.assertEqual(texto_remision(linea), 'Sofá · Tres puestos')
        linea.texto_cliente = 'Sofá a tu medida'
        self.assertEqual(texto_remision(linea), 'Sofá a tu medida')

    def test_conjunto_se_guarda_y_cada_pieza_conserva_su_pedido(self):
        mesa = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Mesa', costo_base=50)
        piezas = [self.fila(conjunto='c-1', conjunto_nombre='Comedor 6 puestos', conjunto_cantidad=1, cantidad=6),
                  self.fila(variante=mesa.pk, grupo_catalogo=None, opcionales=[], tela_modo='no_aplica', cantidad=1,
                            conjunto='c-1', conjunto_nombre='Comedor 6 puestos')]
        d = self.guardar(piezas)
        self.assertEqual([(l['conjunto'], l['conjunto_nombre']) for l in d['lineas']], [('c-1', 'Comedor 6 puestos')] * 2)
        # Un conjunto necesita nombre.
        r = self.api_asesor.post(self.url, {'revision': d['revision'], 'lineas': [self.fila(conjunto='c-2', conjunto_nombre=' ')]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('conjunto_nombre', r.data['lineas'][0])

    def test_un_juego_del_catalogo_trae_sus_piezas(self):
        mesa = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Mesa', costo_base=50)
        juego = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Comedor', costo_base=0)
        ComponenteJuego.objects.create(juego=juego, variante=mesa, cantidad=1)
        ComponenteJuego.objects.create(juego=juego, variante=self.variante, cantidad=6, orden=1)
        r = self.api_asesor.get('/api/productos-venta/catalogo/', {'id': juego.pk})
        piezas = r.data['results'][0]['piezas']
        self.assertEqual([(p['variante'], p['cantidad'], p['tela']) for p in piezas], [(mesa.pk, 1, False), (self.variante.pk, 6, True)])
        # Los opcionales de las piezas también se ofrecen en el conjunto, con su estado inicial.
        usb = CargoVariante.objects.create(variante=mesa, descripcion='USB', valor=5, opcional=True, preseleccionado=True)
        opcionales = self.api_asesor.get('/api/productos-venta/catalogo/', {'id': juego.pk}).data['results'][0]['opcionales']
        self.assertIn({'id': usb.pk, 'descripcion': 'USB · Mesa', 'especial': False, 'preseleccionado': True}, opcionales)
        # El costo base guardado en un conjunto no cuenta (2026-10-15): sigue dividiéndose.
        juego.costo_base = 10
        juego.save()
        self.assertEqual(len(self.api_asesor.get('/api/productos-venta/catalogo/', {'id': juego.pk}).data['results'][0]['piezas']), 2)
        # Con cargos fijos propios del juego no se divide: se agrega entero.
        CargoVariante.objects.create(variante=juego, descripcion='Armado', valor=10)
        self.assertEqual(self.api_asesor.get('/api/productos-venta/catalogo/', {'id': juego.pk}).data['results'][0]['piezas'], [])

    def test_costo_sugerido_para_la_factura(self):
        # Lista 230 por unidad (ver ProductosVentaTests) ÷ multiplicador 2 = 115.
        d = self.guardar()
        self.assertEqual(self.pedir(d).status_code, 201)
        r = self.api_admin.get(f'/api/productos-venta/proveedores/{self.prov.pk}/por-facturar/')
        self.assertEqual(r.status_code, 200, r.data)
        [fila] = r.data['productos']
        self.assertEqual((fila['cantidad'], fila['producto'], fila['detalle']), (2, 'Sofá · Tres puestos', 'Tres puestos'))
        self.assertEqual((fila['costo_sugerido']['valor'], fila['costo_sugerido']['multiplicador']), ('115', '2'))
        self.assertEqual(fila['telas'][0]['referencia'], 'Lino')
        # Con la tela comprada aparte, se descuenta la tela que el catálogo incluía (2 m × 10).
        linea = LineaVenta.objects.get()
        linea.tela_modo = 'aparte'
        linea.save(update_fields=['tela_modo'])
        fila = self.api_admin.get(f'/api/productos-venta/proveedores/{self.prov.pk}/por-facturar/').data['productos'][0]
        self.assertEqual((fila['costo_sugerido']['valor'], fila['costo_sugerido']['tela_descontada']), ('95', '20'))
        # La recepción de un pedido usa la misma sugerencia; sin permiso de facturas no hay acceso.
        recepcion = self.api_admin.get(f"/api/productos-venta/pedidos/{fila['pedido']}/recepcion/").data
        self.assertEqual(recepcion['productos'][0]['costo_sugerido']['valor'], '95')
        self.assertEqual(self.api_asesor.get(f'/api/productos-venta/proveedores/{self.prov.pk}/por-facturar/').status_code, 403)

    def test_tela_con_grupo_y_costo(self):
        prov = ProveedorTela.objects.create(nombre_empresa='Ariatex de prueba')
        aparte = dict(tela_modo='aparte', tela_proveedor=prov.pk, tela_cantidad='4')
        d = self.guardar([self.fila(**aparte)])
        # En un producto de catálogo, el grupo de la tela es el de su precio y el costo, el del grupo.
        self.assertEqual((d['lineas'][0]['tela_grupo'], Decimal(d['lineas'][0]['tela_costo'])), (self.grupo.pk, Decimal(10)))
        otro = GrupoTela.objects.create(nombre='Grupo 3', precio_por_metro=25)
        d = self.guardar([self.fila(id=d['lineas'][0]['id'], tela_grupo=otro.pk, tela_costo='31', **aparte)], revision=d['revision'])
        self.assertEqual((d['lineas'][0]['tela_grupo_nombre'], Decimal(d['lineas'][0]['tela_costo'])), ('Grupo 3', Decimal(31)))
        # Si la pone el proveedor del mueble (tela o cuero), no lleva costo aparte.
        d = self.guardar([self.fila(id=d['lineas'][0]['id'], tela_modo='incluida', tela_costo='31')], revision=d['revision'])
        self.assertIsNone(d['lineas'][0]['tela_costo'])

    def test_se_puede_guardar_sin_productos(self):
        d = self.guardar()
        vacia = self.api_asesor.post(self.url, {'revision': d['revision'], 'lineas': []}, format='json')
        self.assertEqual(vacia.status_code, 200, vacia.data)
        self.assertEqual(vacia.data['lineas'], [])
        self.v.refresh_from_db()
        self.assertEqual((self.v.productos_confirmados, self.v.valor_lista), (False, None))


class DecorativosTests(LottusTestCase):
    """«Cojines incluidos»: el cargo fijo «Decorativos x2» cubre 2 decorativos por unidad del
    producto; en grupo 1 o 2 completos, desde grupo 3 se cobra la diferencia frente a grupo 2."""
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        self.permisos('administrador', ['ALL'])
        self.g2 = GrupoTela.objects.create(nombre='Grupo 2', precio_por_metro=20, orden=2)
        self.g3 = GrupoTela.objects.create(nombre='Grupo 3', precio_por_metro=40, orden=3)
        # Decorativo: (10 + 1 m × precio del grupo) × 2 → grupo 1 = 40, grupo 2 = 60, grupo 3 = 100.
        # El legado sin referencia queda archivado; esta prueba habilita su fixture histórico.
        LineaProducto.objects.filter(slug='decorativos').update(activo=True)
        self.deco = VarianteProducto.objects.create(linea=LineaProducto.objects.get(slug='decorativos'), categoria=self.variante.categoria,
                                                    nombre='Cojín 45 × 45', costo_base=10, metraje_tela=1)

    def incluir(self, **extra):
        # Valor 0 para que las cuentas de estas pruebas midan solo el cupo de decorativos.
        r = self.api_admin.post('/api/listaprecios/cargos/', {'variante': self.variante.pk, 'tipo': 'decorativos', 'valor': 0, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def filas(self):
        return [self.fila(cantidad=1),
                self.fila(variante=self.deco.pk, grupo_catalogo=self.grupo.pk, cantidad=1, opcionales=[]),
                self.fila(variante=self.deco.pk, grupo_catalogo=self.g3.pk, cantidad=2, opcionales=[])]

    def test_elige_los_de_mayor_valor_cubierto(self):
        from listaprecios.decorativos import elegir_incluidos
        # Ejemplo del usuario: A $100 (g1), B $150 (g2), C $200 en g4 que en g2 valdría $160.
        r = elegir_incluidos(2, [('A', Decimal(100)), ('B', Decimal(150)), ('C', Decimal(160))])
        self.assertEqual(r, {'B': {'unidades': 1, 'valor': Decimal(150)}, 'C': {'unidades': 1, 'valor': Decimal(160)}})
        self.assertEqual(elegir_incluidos(0, [('A', Decimal(100))]), {})

    def test_la_venta_descuenta_los_decorativos_incluidos(self):
        sin = self.guardar(self.filas())
        self.assertEqual(Decimal(sin['valor_lista']), Decimal(230 + 40 + 200))  # sin «Cojines incluidos» todo se cobra
        cargo = self.incluir()
        self.assertEqual((cargo['descripcion'], Decimal(cargo['valor']), cargo['opcional']), ('Decorativos x2', Decimal(0), False))
        filas = self.filas()
        for f, l in zip(filas, sin['lineas']):
            f['id'] = l['id']
        d = self.guardar(filas, revision=sin['revision'])
        # Cupo 2 (1 sofá): los dos de grupo 3 (cubren 60 c/u, lo que valen en grupo 2); el de grupo 1 se cobra.
        self.assertEqual(Decimal(d['valor_lista']), Decimal(230 + 40 + 200 - 120))
        sofa, g1, g3 = d['lineas']
        self.assertEqual((sofa['da_decorativos'], g1['decorativos_incluidos'], g3['decorativos_incluidos']),
                         (True, None, {'unidades': 2, 'valor': '120.00'}))
        # Con dos sofás el cupo es 4: también el de grupo 1 queda incluido.
        filas[0]['cantidad'] = 2
        d = self.guardar(filas, revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(460 + 40 + 200 - 160))

    def test_cotizacion_aplica_la_misma_regla(self):
        self.incluir()
        lineas = [{'variante': self.variante.pk, 'grupo_tela': self.grupo.pk, 'cantidad': 1, 'precio_unitario': 230, 'linea_nombre': 'Sofá', 'variante_nombre': 'Tres puestos'},
                  {'variante': self.deco.pk, 'grupo_tela': self.g3.pk, 'cantidad': 3, 'precio_unitario': 100, 'linea_nombre': 'Decorativos', 'variante_nombre': 'Cojín'}]
        r = self.api_admin.post('/api/listaprecios/cotizaciones/', {'cliente_nombre': 'Ana', 'descuento': 0, 'lineas': lineas}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        from listaprecios.models import Cotizacion
        c = Cotizacion.objects.get(pk=r.data['id'])
        deco = c.lineas.get(variante=self.deco)
        self.assertEqual((deco.incluido, deco.subtotal, c.subtotal), (Decimal(120), Decimal(180), Decimal(410)))

    def test_el_cargo_tiene_valor_sugerido_es_editable_y_unico(self):
        r = self.api_admin.post('/api/listaprecios/cargos/', {'variante': self.variante.pk, 'tipo': 'decorativos'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        # 2 × el decorativo de mayor costo en el último grupo incluido: 2 × (10 + 1 m × 20) = 60.
        self.assertEqual((r.data['descripcion'], Decimal(r.data['valor']), r.data['opcional']), ('Decorativos x2', Decimal(60), False))
        url = f"/api/listaprecios/cargos/{r.data['id']}/"
        cambio = self.api_admin.patch(url, {'valor': 5000, 'descripcion': 'Cojines x2'}, format='json')
        self.assertEqual((cambio.status_code, Decimal(cambio.data['valor']), cambio.data['tipo']), (200, Decimal(5000), 'decorativos'))
        self.assertEqual(self.api_admin.patch(url, {'tipo': ''}, format='json').status_code, 400)
        self.assertEqual(self.api_admin.post('/api/listaprecios/cargos/', {'variante': self.variante.pk, 'tipo': 'decorativos'}, format='json').status_code, 400)
        self.assertEqual(self.api_admin.delete(url).status_code, 204)

    def test_como_opcional_solo_cubre_si_se_elige(self):
        cargo = self.incluir(opcional=True, preseleccionado=False)
        filas = self.filas()
        d = self.guardar(filas)
        self.assertEqual(Decimal(d['valor_lista']), Decimal(230 + 40 + 200))  # no elegido: no cubre
        filas[0]['opcionales'] = [*filas[0]['opcionales'], cargo['id']]
        for f, l in zip(filas, d['lineas']):
            f['id'] = l['id']
        d = self.guardar(filas, revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(230 + 40 + 200 - 120))
        self.assertTrue(d['lineas'][0]['da_decorativos'])

    def test_catalogo_informa_cupo_y_tope_y_se_actualiza(self):
        self.vincular_subcategorias_catalogo(self.variante.linea)
        self.vincular_subcategorias_catalogo(self.deco.linea)
        def catalogo():
            lineas = self.api_admin.get('/api/listaprecios/catalogo/').data
            return {v['id']: v for l in lineas for v in l['variantes']}
        self.assertEqual(catalogo()[self.variante.pk]['decorativos_incluidos'], 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.incluir()
        cat = catalogo()  # la caché se descartó al confirmar el cambio
        self.assertEqual(cat[self.variante.pk]['decorativos_incluidos'], 2)
        topes = {f['grupo']: Decimal(str(f['tope_incluido'])) for f in cat[self.deco.pk]['precios']}
        self.assertEqual(topes, {self.grupo.pk: Decimal(40), self.g2.pk: Decimal(60), self.g3.pk: Decimal(60)})


class TransportesVentaTests(LottusTestCase):
    """2026-10-21: el transporte se cobra por envío; las piezas de un conjunto llevan uno solo."""
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        self.permisos('administrador', ['ALL'])
        # Sofá: (100 + 2 m × 10 + 5 fijo − 10 «Sin tapa») × 2 = 230; con transporte 50 → 330 por unidad.
        CargoVariante.objects.create(variante=self.variante, descripcion='Transporte', valor=50, tipo='transporte', unidades_por_transporte=2)
        self.mesa = VarianteProducto.objects.create(linea=self.variante.linea, categoria=self.variante.categoria, nombre='Mesa', costo_base=50)
        CargoVariante.objects.create(variante=self.mesa, descripcion='Transporte', valor=30, tipo='transporte')  # mesa: (50 + 30) × 2 = 160

    def test_cupo_por_transporte_en_una_linea(self):
        d = self.guardar([self.fila(cantidad=3)])
        # 3 sofás con cupo 2: dos transportes; se descuenta uno (100).
        self.assertEqual(Decimal(d['valor_lista']), Decimal(3 * 330 - 100))
        self.assertEqual(d['lineas'][0]['transporte_compartido'], {'transportes': 2, 'valor': '100.00'})

    def test_las_piezas_de_un_conjunto_cobran_un_solo_transporte(self):
        piezas = [self.fila(cantidad=1, conjunto='c-1', conjunto_nombre='Sala comedor'),
                  self.fila(variante=self.mesa.pk, grupo_catalogo=None, opcionales=[], tela_modo='no_aplica', cantidad=1,
                            conjunto='c-1', conjunto_nombre='Sala comedor')]
        d = self.guardar(piezas)
        # Se cobra el transporte mayor (sofá, 100); el de la mesa (60) no.
        self.assertEqual(Decimal(d['valor_lista']), Decimal(330 + 160 - 60))
        self.assertEqual([l['transporte_compartido'] for l in d['lineas']], [None, {'transportes': 0, 'valor': '60.00'}])
        # Sueltos, cada producto lleva el suyo.
        sueltos = [dict(p, conjunto='', conjunto_nombre='') for p in piezas]
        for f, l in zip(sueltos, d['lineas']):
            f['id'] = l['id']
        d = self.guardar(sueltos, revision=d['revision'])
        self.assertEqual(Decimal(d['valor_lista']), Decimal(330 + 160))
