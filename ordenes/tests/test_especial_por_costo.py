"""(2026-10-28) «Agregar especial»: producto fuera de la lista con su costo total; el precio de lista
= (costo + consumo × costo del grupo) × multiplicador general. Sirve para pedidos al proveedor y de
tela. Y el detalle de la venta en Nómina muestra todo lo pedido, los abonos y la dirección."""
from datetime import date
from decimal import Decimal

from listaprecios.models import GrupoTela, Multiplicador
from ordenes import nomina
from ordenes.models import DireccionEntrega, LineaNomina, OrdenPedido, PagoReciboCaja, PedidoTela, ProveedorTela, ReciboCaja
from ordenes.productos_venta import costo_sugerido
from ordenes.tests import test_productos_venta


class EspecialPorCostoTests(test_productos_venta.LottusTestCase):
    _base = test_productos_venta.ProductosVentaTests
    setUp = _base.setUp
    guardar = _base.guardar
    pedir = _base.pedir

    def especial(self, **extra):
        # Grupo 1: $10 por metro; multiplicador general ×2.
        return {'variante': None, 'producto_nombre': 'Mueble TV a medida', 'cantidad': 2, 'referencia': self.ref.pk,
                'costo_especial': '1000', 'grupo_catalogo': self.grupo.pk, 'metraje_especial': '3',
                'texto_proveedor': 'Según plano', 'tela_modo': 'incluida', 'tela_referencia': 'Lino', 'tela_color': 'Arena', **extra}

    def test_el_vendedor_agrega_un_especial_y_el_precio_sale_del_costo(self):
        d = self.guardar([self.especial()])  # el asesor no tiene AJUSTAR_PRECIO_LISTA_VENTA
        l = self.v.lineas.get()
        # (1.000 + 3 m × $10) × 2 = 2.060 por unidad; costo 1.030.
        self.assertEqual((l.precio_lista_unitario, l.costo_estimado, l.grupo_tela), (Decimal(2060), Decimal(1030), 'Grupo 1'))
        self.assertEqual(Decimal(d['valor_lista']), Decimal(4120))
        fila = d['lineas'][0]
        self.assertEqual((fila['costo_especial'], fila['metraje_especial']), ('1000', '3'))
        self.assertEqual(costo_sugerido(l)['valor'], '1030')  # lista ÷ multiplicador, para la factura

    def test_sin_tela_y_validaciones(self):
        r = self.api_asesor.post(f'/api/ventas/{self.v.pk}/productos/calcular/',
                                 self.especial(grupo_catalogo=None, metraje_especial=None, tela_modo='no_aplica'), format='json')
        self.assertEqual((r.status_code, r.data['precio_lista_unitario']), (200, '2000.00'))
        calcular = lambda **e: self.api_asesor.post(f'/api/ventas/{self.v.pk}/productos/calcular/', self.especial(**e), format='json')
        self.assertEqual(calcular(costo_especial='1000.50').status_code, 400)  # sin centavos
        self.assertIn('metraje_especial', calcular(metraje_especial=None).data)  # grupo sin consumo
        self.assertIn('grupo_catalogo', calcular(grupo_catalogo=None).data)  # consumo sin grupo
        self.assertEqual(calcular(opcionales=[self.opcional.pk]).status_code, 400)  # sin cargos
        self.assertEqual(calcular(variante=self.variante.pk).status_code, 400)  # la lista ya tiene su costo
        cuero = GrupoTela.objects.create(nombre='Cuero', tipo='cuero', precio_por_metro=2)
        r = calcular(grupo_catalogo=cuero.pk, metraje_especial='100', tela_modo='no_aplica')
        self.assertEqual(r.data['precio_lista_unitario'], '2400.00')  # (1.000 + 100 dm × 2) × 2

    def test_conserva_su_precio_si_cambia_el_multiplicador(self):
        d = self.guardar([self.especial()])
        Multiplicador.objects.filter(es_general=True).update(valor=3)
        fila = {k: v for k, v in self.especial(id=d['lineas'][0]['id']).items()}
        self.guardar([fila], revision=d['revision'])
        self.assertEqual(self.v.lineas.get().precio_lista_unitario, Decimal(2060))
        # Cambiar el costo sí lo recalcula (con el multiplicador de hoy).
        d = self.guardar([{**fila, 'costo_especial': '2000'}], revision=d['revision'] + 1)
        self.assertEqual(self.v.lineas.get().precio_lista_unitario, Decimal(6090))  # (2.000 + 30) × 3

    def test_pedido_al_proveedor_y_de_tela(self):
        ariatex = ProveedorTela.objects.create(nombre_empresa='Ariatex ficticia')
        DireccionEntrega.objects.create(nombre=self.prov.nombre_empresa, detalles='Calle ficticia 1')
        d = self.guardar([self.especial(tela_modo='aparte', tela_proveedor=ariatex.pk)])
        fila = d['lineas'][0]
        self.assertEqual(Decimal(fila['tela_cantidad']), Decimal(6))  # 3 m × 2 unidades
        r = self.pedir(d)
        self.assertEqual(r.status_code, 201, r.data)
        orden = OrdenPedido.objects.get(pk=r.data['ordenes'][0])
        self.assertEqual((orden.proveedor_id, orden.detalles.get().cantidad), (self.prov.pk, 2))
        r = self.api_admin.post('/api/pedidos-telas/', {
            'proveedor': ariatex.pk, 'direccion_entrega': 'Lottus', 'estado': 'Pendiente', 'venta': self.v.pk, 'orden_asociada_id': orden.pk,
            'detalles': [{'tela': 'Lino - Color: Arena', 'cantidad': '6', 'linea_venta': fila['id']}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)


class NominaVentaDetalleTests(test_productos_venta.LottusTestCase):
    _base = test_productos_venta.ProductosVentaTests
    setUp = _base.setUp
    guardar = _base.guardar
    pedir = _base.pedir
    fila = _base.fila

    def test_muestra_todo_lo_pedido_abonos_y_direccion(self):
        cliente = self.v.cliente
        cliente.direccion, cliente.barrio, cliente.ciudad = 'Calle 10 # 5-20', 'El Prado', 'Barranquilla'
        cliente.save()
        d = self.guardar()
        orden = self.pedir(d).data['ordenes'][0]
        ariatex = ProveedorTela.objects.create(nombre_empresa='Ariatex ficticia')
        pt = PedidoTela.objects.create(id=7001, usuario=self.admin, proveedor=ariatex, direccion_entrega='Fábrica', orden_asociada_id=orden, estado='Anulado')
        pt.detalles.create(tela='Lino Arena', cantidad=4, linea_venta=self.v.lineas.get())
        rc = ReciboCaja.objects.create(id=9101, venta=self.v)
        PagoReciboCaja.objects.create(recibo=rc, metodo_pago='Davivienda', valor=100, estado='Pendiente')
        cierre = nomina.crear_cierre(self.admin, date(2026, 10, 1), date(2026, 10, 5))
        com = LineaNomina.objects.get(asesor_cierre__cierre=cierre, tipo='comision')
        r = self.api_admin.get(f'/api/nomina/lineas/{com.pk}/venta/')
        self.assertEqual(r.status_code, 200, r.data)
        v = r.data['venta']
        self.assertEqual((v['direccion'], v['barrio'], v['ciudad']), ('Calle 10 # 5-20', 'El Prado', 'Barranquilla'))
        [op] = r.data['pedidos']
        self.assertEqual((op['id'], op['estado'], op['detalles'][0]['cantidad']), (orden, 'pendiente', 2))
        [tela] = r.data['pedidos_tela']
        self.assertEqual((tela['id'], tela['estado'], tela['orden'], tela['detalles'][0]['unidad']), (7001, 'Anulado', orden, 'm'))
        self.assertEqual([p['estado'] for p in r.data['pagos']], ['Pendiente'])
