"""Tela por producto, pedido de telas desde la venta y gestión de la venta (2026-10-08)."""
from datetime import date, timedelta
from decimal import Decimal

from listaprecios.models import CategoriaLista, GrupoTela, LineaProducto, VarianteProducto
from ordenes import business_time
from ordenes.gestion_venta import DIAS_LIMITE, estado_gestion
from ordenes.models import DetallePedidoTela, DireccionEntrega, OrdenPedido, PedidoTela, ProveedorTela, Venta
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase


class GestionYTelasTests(LottusTestCase):
    # Mismo escenario que ProductosVentaTests, sin repetir sus casos.
    fila = base.ProductosVentaTests.fila
    guardar = base.ProductosVentaTests.guardar
    pedir = base.ProductosVentaTests.pedir

    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        self.ariatex = ProveedorTela.objects.create(nombre_empresa='Ariatex ficticia')
        DireccionEntrega.objects.create(nombre=self.prov.nombre_empresa, detalles='Calle ficticia 1')
        self.v.fecha_venta = business_time.hoy()
        self.v.save(update_fields=['fecha_venta'])

    def tela_aparte(self, **extra):
        return self.fila(**{'tela_modo': 'aparte', 'tela_referencia': 'Lino', 'tela_color': 'Arena 03', 'tela_proveedor': self.ariatex.pk, **extra})

    def pedir_telas(self, d, cliente=None, detalle=None, **extra):
        """Igual que el formulario de /telas, con la venta y el producto de cada fila."""
        linea = d['lineas'][0]
        body = {'proveedor': self.ariatex.pk, 'direccion_entrega': linea['tela_direccion_sugerida'] or 'Lottus', 'estado': 'Pendiente',
                'orden_asociada_id': linea['tela_orden'], 'venta': self.v.pk,
                'detalles': [detalle or {'tela': 'Lino - Color: Arena 03', 'cantidad': '4', 'linea_venta': linea['id']}], **extra}
        return (cliente or self.api_admin).post('/api/pedidos-telas/', body, format='json')

    def gestion(self, accion, revision, cliente=None):
        return (cliente or self.api_asesor).post(f'/api/ventas/{self.v.pk}/gestion/', {'revision': revision, 'accion': accion}, format='json')

    def rechazo(self, filas):
        r = self.api_asesor.post(self.url, {'revision': self.api_asesor.get(self.url).data['revision'], 'lineas': filas}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        return set(r.data['lineas'][0])

    def test_no_guarda_un_producto_con_la_tela_incompleta_y_dice_que_falta(self):
        self.assertEqual(self.rechazo([self.fila(tela_modo='')]), {'tela_modo'})
        self.assertEqual(self.rechazo([self.fila(tela_referencia='', tela_color='')]), {'tela_referencia', 'tela_color'})
        self.assertEqual(self.rechazo([self.tela_aparte(tela_proveedor=None)]), {'tela_proveedor'})
        # El texto para el cliente y la remisión es opcional (2026-10-15).
        self.assertEqual(self.rechazo([self.fila(texto_cliente='', texto_proveedor='')]), {'texto_proveedor'})
        d = self.guardar([self.tela_aparte()])
        linea = d['lineas'][0]
        self.assertEqual(Decimal(linea['tela_cantidad']), Decimal(4))  # 2 m por unidad × 2 unidades
        self.assertEqual((linea['tela_material'], linea['tela_unidad']), ('tela', 'm'))
        self.assertEqual(linea['tela_proveedor_nombre'], 'Ariatex ficticia')
        self.assertEqual(linea['tela_direccion_sugerida'], f'{self.prov.nombre_empresa} - Calle ficticia 1')
        self.assertTrue(any('falta pedir la tela' in p for p in d['gestion']['pendientes']))
        mesa = VarianteProducto.objects.create(linea=LineaProducto.objects.create(nombre='Mesa', slug='mesa'),
                                               categoria=CategoriaLista.objects.create(nombre='Comedor', slug='comedor'), nombre='Centro', costo_base=50)
        d = self.guardar([self.fila(variante=mesa.pk, grupo_catalogo=None, opcionales=[], tela_modo='', tela_referencia='ignorada')], revision=d['revision'])
        self.assertEqual((d['lineas'][0]['tela_modo'], d['lineas'][0]['tela_referencia']), ('no_aplica', ''))

    def test_cuero_en_decimetros_sin_cantidad_sugerida(self):
        cuero = dict(tela_material='cuero', tela_referencia='Nappa', tela_color='Miel')
        # Sin grupo de cuero: falta el grupo y su costo por decímetro, además de la cantidad.
        self.assertEqual(self.rechazo([self.tela_aparte(**cuero)]), {'tela_cantidad', 'tela_grupo', 'tela_costo'})
        grupo = GrupoTela.objects.create(nombre='Cuero importado', tipo='cuero', precio_por_metro=3500)
        self.assertEqual(self.rechazo([self.tela_aparte(tela_grupo=grupo.pk, **cuero)]), {'tela_cantidad'})
        linea = self.guardar([self.tela_aparte(tela_cantidad='1200', tela_grupo=grupo.pk, **cuero)])['lineas'][0]
        self.assertEqual((linea['tela_material'], linea['tela_unidad'], Decimal(linea['tela_cantidad'])), ('cuero', 'dm', Decimal(1200)))
        # El costo por decímetro sale del grupo de la lista de precios y se puede corregir.
        self.assertEqual((linea['tela_grupo'], Decimal(linea['tela_costo']), linea['tela_grupo_nombre']), (grupo.pk, Decimal(3500), 'Cuero importado'))
        # Un grupo de tela no sirve para cuero.
        self.assertEqual(self.rechazo([self.tela_aparte(tela_cantidad='1200', tela_grupo=self.grupo.pk, **cuero)]), {'tela_grupo'})

    def test_tela_incluida_no_guarda_proveedor_ni_cantidad(self):
        d = self.guardar([self.fila(tela_modo='incluida', tela_proveedor=self.ariatex.pk, tela_cantidad='9')])
        self.assertEqual((d['lineas'][0]['tela_proveedor'], d['lineas'][0]['tela_cantidad']), (None, None))

    def test_servicios_y_ajustes_suman_o_restan_al_precio_de_lista(self):
        filas = [self.fila(),
                 {'tipo': 'transporte', 'producto_nombre': 'Envío a Chía', 'cantidad': 1, 'precio_lista_override': '50'},
                 {'tipo': 'articulo', 'producto_nombre': 'Jarrón decorativo', 'cantidad': 2, 'precio_lista_override': '20'},
                 {'tipo': 'ajuste', 'producto_nombre': 'No lleva cojines', 'cantidad': 1, 'precio_lista_override': '-30'}]
        d = self.guardar(filas)
        # 460 de productos + 50 + 2×20 − 30
        self.assertEqual(Decimal(d['valor_lista']), Decimal(520))
        tipos = {l['tipo']: l for l in d['lineas']}
        self.assertEqual((tipos['transporte']['por_pedir'], tipos['articulo']['texto_cliente']), (0, 'Jarrón decorativo'))
        lineas = {l.tipo: l for l in self.v.lineas.all()}
        self.assertEqual(lineas['ajuste'].subtotal, Decimal(-30))
        self.assertEqual(sum(l.subtotal for l in self.v.lineas.all()), self.v.valor_total)
        self.assertEqual(d['gestion']['pendientes'], [p for p in d['gestion']['pendientes'] if 'Producto 1' in p])
        # No se piden al proveedor; un transporte no puede ser negativo y todo necesita descripción.
        r = self.api_asesor.post(self.url + 'pedidos/', {'revision': d['revision'], 'fecha_esperada': '2026-10-20',
                                                         'lineas': [{'linea': tipos['transporte']['id'], 'cantidad': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.rechazo([{'tipo': 'transporte', 'producto_nombre': '', 'cantidad': 1, 'precio_lista_override': '-5'}]),
                         {'producto_nombre', 'precio_lista_override'})

    def test_pedir_telas_desde_la_venta_una_vez_y_ligado_al_producto(self):
        d = self.guardar([self.tela_aparte()])
        op = self.pedir(d).data['ordenes'][0]
        d = self.api_asesor.get(self.url).data
        self.assertEqual(d['lineas'][0]['tela_orden'], op)
        self.assertEqual(self.pedir_telas(d, cliente=self.api_asesor).status_code, 403)
        r = self.pedir_telas(d, detalle={'tela': '[CUERO] Nappa - Color: Miel', 'cantidad': '1200', 'linea_venta': d['lineas'][0]['id']})
        self.assertEqual(r.status_code, 201, r.data)
        pedido = PedidoTela.objects.get()
        self.assertEqual((pedido.venta_id, pedido.orden_asociada_id, pedido.proveedor_id), (self.v.pk, op, self.ariatex.pk))
        self.assertEqual(pedido.direccion_entrega, f'{self.prov.nombre_empresa} - Calle ficticia 1')
        detalle = DetallePedidoTela.objects.get()
        self.assertEqual((detalle.linea_venta_id, detalle.cantidad), (d['lineas'][0]['id'], Decimal(1200)))
        d = self.api_asesor.get(self.url).data
        linea = d['lineas'][0]
        # El producto queda con lo que realmente se pidió.
        self.assertEqual((linea['tela_material'], linea['tela_referencia'], linea['tela_color'], Decimal(linea['tela_cantidad'])), ('cuero', 'Nappa', 'Miel', Decimal(1200)))
        self.assertEqual(linea['tela_pedidos'][0]['id'], pedido.pk)
        self.assertEqual(self.pedir_telas(d).status_code, 400)
        self.assertEqual(PedidoTela.objects.count(), 1)
        # Ya pedida: no se cambia la tela desde el producto.
        linea['tela_referencia'] = 'Otra'
        resp = self.api_asesor.post(self.url, {'revision': d['revision'], 'lineas': [linea]}, format='json')
        self.assertEqual(resp.status_code, 400)
        # Aparece en la lista de pedidos de tela con su venta.
        self.assertEqual(self.api_admin.get('/api/pedidos-telas/').data['results'][0]['venta_id'], self.v.pk)

    def test_no_pide_tela_de_una_venta_que_no_ve(self):
        d = self.guardar([self.tela_aparte()])
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS', 'VER_PRECIOS_VENTA', 'EDITAR_PRODUCTOS_VENTA', 'CREAR_PEDIDO_TELA'])
        r = self.pedir_telas(d, cliente=self.api(self.otro))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(PedidoTela.objects.count(), 0)

    def test_finalizar_exige_todo_pedido_y_se_reabre_si_cambian_los_productos(self):
        d = self.guardar([self.tela_aparte()])
        r = self.gestion('finalizar', d['revision'])
        self.assertEqual(r.status_code, 409)
        self.assertIn('falta pedirlo al proveedor', r.data['error'] if 'error' in r.data else str(r.data))
        self.assertEqual(self.pedir(d).status_code, 201)
        self.assertEqual(self.pedir_telas(self.api_asesor.get(self.url).data).status_code, 201)
        d = self.api_asesor.get(self.url).data
        self.assertEqual(d['gestion']['pendientes'], [])
        r = self.gestion('finalizar', d['revision'])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['gestion']['estado'], 'finalizada')
        self.v.refresh_from_db()
        self.assertTrue(self.v.estado_pedidos)
        self.assertEqual(self.v.gestion_finalizada_por, self.asesor)
        lista = self.api_admin.get('/api/ventas/').data
        fila = next(x for x in (lista['results'] if isinstance(lista, dict) else lista) if x['id'] == self.v.pk)
        self.assertEqual(fila['gestion'], 'finalizada')
        # Agregar otro producto después de finalizar la devuelve a pendiente.
        d = self.api_asesor.get(self.url).data
        d = self.guardar(d['lineas'] + [self.fila(tela_modo='incluida', tela_referencia='Cuero miel')], revision=d['revision'])
        self.assertEqual(d['gestion']['estado'], 'pendiente')
        self.v.refresh_from_db()
        self.assertFalse(self.v.estado_pedidos)

    def test_reabrir_y_permiso(self):
        d = self.guardar([self.fila(tela_modo='incluida', tela_referencia='Lino')])
        self.pedir(d)
        d = self.api_asesor.get(self.url).data
        self.assertEqual(self.gestion('finalizar', d['revision'], cliente=self.api(self.otro)).status_code, 404)
        self.assertEqual(self.gestion('finalizar', d['revision']).status_code, 200)
        r = self.gestion('reabrir', d['revision'])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['gestion']['estado'], 'pendiente')

    def test_estados_de_gestion(self):
        hoy = date(2026, 10, 20)
        v = Venta(fecha_venta=hoy - timedelta(days=DIAS_LIMITE), estado='pendiente', estado_pedidos=False)
        self.assertEqual(estado_gestion(v, hoy), 'pendiente')
        v.fecha_venta = hoy - timedelta(days=DIAS_LIMITE + 1)
        self.assertEqual(estado_gestion(v, hoy), 'atrasada')
        v.estado = 'entregado'
        self.assertEqual(estado_gestion(v, hoy), 'finalizada')
        v.estado = 'anulada'
        self.assertIsNone(estado_gestion(v, hoy))

    def test_orden_desde_la_venta_con_observacion_fecha_y_estado_de_tela(self):
        d = self.guardar([self.tela_aparte()])
        body = {'revision': d['revision'], 'fecha_esperada': '2026-10-20', 'lineas': [{'linea': d['lineas'][0]['id'], 'cantidad': 2}],
                'ordenes': [{'proveedor': self.prov.pk, 'fecha_esperada': '2026-11-02', 'observacion': 'Entregar en la mañana'}]}
        r = self.api_asesor.post(self.url + 'pedidos/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['detalle'][0]['proveedor'], self.prov.pk)
        orden = OrdenPedido.objects.get(pk=r.data['ordenes'][0])
        self.assertEqual((str(orden.fecha_esperada), orden.observacion, orden.tela), ('2026-11-02', 'Entregar en la mañana', 'Por pedir'))
        # Al pedir la tela del producto, la orden queda con la tela "Pedida" en /ordenes.
        self.assertEqual(self.pedir_telas(self.api_asesor.get(self.url).data).status_code, 201)
        orden.refresh_from_db()
        self.assertEqual(orden.tela, 'Pedida')

    def test_estado_de_tela_de_la_orden_segun_los_productos(self):
        d = self.guardar([self.fila(tela_modo='incluida', tela_referencia='Lino')])
        orden = OrdenPedido.objects.get(pk=self.pedir(d).data['ordenes'][0])
        self.assertEqual(orden.tela, 'Sin tela')
        # Tela pedida antes que la orden: la orden nace con la tela "Pedida".
        self.v.lineas.all().delete(); OrdenPedido.objects.all().delete()
        d = self.guardar([self.tela_aparte()], revision=self.api_asesor.get(self.url).data['revision'])
        self.assertEqual(self.pedir_telas(d).status_code, 201)
        d = self.api_asesor.get(self.url).data
        orden = OrdenPedido.objects.get(pk=self.pedir(d).data['ordenes'][0])
        self.assertEqual(orden.tela, 'Pedida')

    def test_pedido_anterior_se_vincula_aunque_cambie_la_referencia_o_se_marca_ajeno(self):
        from datetime import date as _date
        from ordenes.models import DetallePedido
        otra_ref = self.referencia(self.prov, nombre='Sobre ficticio')
        orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=self.v, fecha_esperada=_date.today())
        sobre = DetallePedido.objects.create(orden=orden, referencia=otra_ref, cantidad=1, especificaciones='Sobre en vidrio')
        ajeno = DetallePedido.objects.create(orden=orden, referencia=otra_ref, cantidad=1, especificaciones='Otro')
        d = self.guardar()
        self.assertEqual(len(d['pedidos_sin_vincular']), 2)
        r = self.api_asesor.post(self.url + 'vincular-pedidos/', {'revision': d['revision'], 'vinculos': [
            {'detalle': sobre.pk, 'linea': d['lineas'][0]['id']}, {'detalle': ajeno.pk, 'linea': None}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['pedidos_sin_vincular'], [])
        self.assertEqual(r.data['lineas'][0]['por_pedir'], 1)
        ajeno.refresh_from_db()
        self.assertTrue(ajeno.ignorar_vinculo)
        # Ya no bloquea pedir lo que falta.
        self.assertEqual(self.pedir(r.data, cantidad=1).status_code, 201)
