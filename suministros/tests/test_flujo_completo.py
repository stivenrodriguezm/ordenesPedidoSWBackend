"""Recorrido completo con los mismos identificadores y un responsable por
transición (P11-04 · F03): cotización → venta → orden de pedido → recepción
por factura (parcial y luego completa) → remisión → despacho → entrega parcial
→ segunda remisión confirmada por la oficina (transportista externo) → venta
entregada. Todo por la API, con los permisos de cada rol."""
from datetime import date
from decimal import Decimal

from listaprecios.models import CategoriaLista, Cotizacion, LineaCotizacion, LineaProducto, VarianteProducto
from ordenes.models import DetallePedido, OrdenPedido, Venta
from ordenes.tests.utils import LottusTestCase
from suministros.models import Inventario, MovimientoInventario, NovedadEntrega, RemisionEvento, RemisionSuministro


class FlujoCompletoTests(LottusTestCase):
    def setUp(self):
        self.vendedor = self.crear_usuario('vendedora', role='vendedor')
        self.auxiliar = self.crear_usuario('auxiliar', role='auxiliar')
        self.transportador = self.crear_usuario('transporte', role='transportador')
        self.permisos('vendedor', [
            'VER_LISTA_PRECIOS', 'CREAR_VENTA', 'VER_VENTAS', 'VER_PROPIAS_VENTAS',
            'CREAR_REMISION', 'VER_REMISIONES', 'CAMBIAR_ESTADO_REMISION', 'EDITAR_ESTADO_VENTA',
        ])
        self.permisos('auxiliar', ['CREAR_ORDEN', 'VER_ORDENES', 'VER_TODAS_ORDENES', 'CREAR_FACTURA', 'VER_FACTURAS'])
        self.prov = self.proveedor('Fábrica ficticia')
        self.ref = self.referencia(self.prov, 'Silla Altus')
        cat = CategoriaLista.objects.create(nombre='Comedores', slug='comedores')
        linea = LineaProducto.objects.create(nombre='Altus', slug='altus')
        self.variante = VarianteProducto.objects.create(linea=linea, categoria=cat, nombre='Silla', costo_base=Decimal('100000'))
        self.cli = self.cliente(cedula='flujo-001', nombre='Cliente del flujo')

    def facturar(self, numero, cantidad, linea_id):
        r = self.api(self.auxiliar).post('/api/suministros/facturas/', {
            'id_manual': numero, 'proveedor': self.prov.pk, 'valor': str(100 * cantidad),
            'productos': [{'referencia': self.ref.pk, 'costo': '100', 'cantidad': cantidad, 'detalle_pedido': linea_id}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_de_la_cotizacion_a_la_entrega(self):
        vend, aux, trans = self.api(self.vendedor), self.api(self.auxiliar), self.api(self.transportador)

        # 1. Cotización aceptada → venta con su línea (vendedora).
        cot = Cotizacion.objects.create(numero='COT-FLUJO', asesor=self.vendedor, cliente=self.cli, estado='aceptada',
                                        subtotal=Decimal('600000'), total=Decimal('600000'))
        LineaCotizacion.objects.create(cotizacion=cot, variante=self.variante, linea_nombre='Altus', variante_nombre='Silla',
                                       cantidad=2, precio_unitario=Decimal('300000'), subtotal=Decimal('600000'))
        r = vend.post(f'/api/listaprecios/cotizaciones/{cot.id}/convertir-a-venta/', format='json')
        self.assertEqual(r.status_code, 201, r.data)
        venta = Venta.objects.get(pk=r.data['venta_id'])
        linea_venta = venta.lineas.get()

        # 2. Orden de pedido ligada a la línea de venta (auxiliar).
        r = aux.post('/api/ordenes-pedido/', {
            'proveedor': self.prov.pk, 'venta': venta.pk, 'fecha_esperada': str(date.today()),
            'detalles': [{'referencia': self.ref.pk, 'cantidad': 2, 'especificaciones': 'Tela gris', 'linea_venta': linea_venta.pk}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        orden = OrdenPedido.objects.get(venta=venta)
        detalle = DetallePedido.objects.get(orden=orden)
        self.assertEqual(detalle.linea_venta, linea_venta)

        # 3. Recepción por factura: llega 1 de 2, luego la otra (auxiliar).
        self.facturar('FAC-1', 1, detalle.pk)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'pendiente')
        self.facturar('FAC-2', 1, detalle.pk)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'recibido')
        u1, u2 = Inventario.objects.filter(detalle_pedido=detalle).order_by('pk')
        self.assertTrue(all(u.venta_id == venta.pk and u.pedido_id == orden.pk for u in (u1, u2)))

        # 4. Remisión (vendedora) → despacho y entrega parcial (transportador asignado).
        r = vend.post('/api/suministros/remisiones/', {
            'ventas': [venta.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [u1.pk, u2.pk],
            'transportador_usuario': self.transportador.pk,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rem1 = RemisionSuministro.objects.get(pk=r.data['id'])
        self.assertEqual(trans.patch(f'/api/suministros/remisiones/{rem1.pk}/', {'estado': 'despachada'}, format='json').status_code, 200)
        r = trans.patch(f'/api/suministros/remisiones/{rem1.pk}/', {
            'estado': 'finalizada', 'no_entregados': [{'inventario': u2.pk, 'motivo': 'rechazado', 'detalle': 'Golpe en el espaldar'}],
            'cerrar_ventas': [venta.pk],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        venta.refresh_from_db()
        self.assertEqual(venta.estado, 'pendiente')

        # 5. Lo pendiente vuelve a sugerirse; la segunda remisión la confirma la oficina
        #    (transportista externo, D04b) y cierra la venta.
        datos = vend.get(f'/api/suministros/remisiones/datos-ventas/?ids={venta.pk}').data[0]
        self.assertEqual([i['id_referencia'] for i in datos['inventario'] if i['seleccionable']], [u2.pk])
        r = vend.post('/api/suministros/remisiones/', {
            'ventas': [venta.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [u2.pk], 'transportador': 'Externo ficticio',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rem2 = r.data['id']
        r = vend.patch(f'/api/suministros/remisiones/{rem2}/', {'estado': 'finalizada', 'cerrar_ventas': [venta.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        venta.refresh_from_db()
        self.assertEqual(venta.estado, 'entregado')

        # 6. Trazabilidad: mismos identificadores y un responsable en cada paso.
        cot.refresh_from_db()
        self.assertEqual(cot.venta_asociada_id, venta.pk)
        self.assertEqual(u2.detalle_pedido.linea_venta.venta_id, venta.pk)
        pasos = list(MovimientoInventario.objects.filter(item=u2).values_list('tipo', 'usuario__username', 'documento'))
        self.assertEqual(pasos, [
            ('ingreso', 'auxiliar', f'factura:{u2.factura_id}'),
            ('reserva', 'vendedora', f'remision:{rem1.pk}'),
            ('despacho', 'transporte', f'remision:{rem1.pk}'),
            ('liberacion', 'transporte', f'remision:{rem1.pk}'),
            ('reserva', 'vendedora', f'remision:{rem2}'),
            ('entrega', 'vendedora', f'remision:{rem2}'),
        ])
        self.assertEqual(NovedadEntrega.objects.get().usuario, self.transportador)
        eventos = list(RemisionEvento.objects.filter(remision__ventas=venta).order_by('id').values_list('tipo', 'usuario__username'))
        self.assertEqual(eventos, [('creada', 'vendedora'), ('despachada', 'transporte'), ('finalizada', 'transporte'),
                                   ('creada', 'vendedora'), ('finalizada', 'vendedora')])
