"""Recepción vinculada a la orden de pedido y entrega parcial (P11-01, P11-03 · D04).

Aceptación del plan: recibir 2 de 3 deja 1 pendiente; facturar no duplica
inventario; entregar parcialmente conserva pendientes y su motivo. Las
carreras con conexiones reales viven en ordenes/tests/test_concurrencia.py."""
from datetime import date

from ordenes.models import DetallePedido, OrdenPedido, RegistroAuditoria
from ordenes.tests.utils import LottusTestCase
from suministros.models import FacturaProveedor, Inventario, NovedadEntrega, RemisionItemManual, RemisionSuministro


class RecepcionTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.c = self.api(self.admin)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)
        self.venta_a = self.venta(self.admin)
        self.orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=self.venta_a,
                                                fecha_esperada=date.today())
        self.linea = DetallePedido.objects.create(orden=self.orden, referencia=self.ref, cantidad=3, especificaciones='-')

    def facturar(self, id_manual, cantidad, linea=None, **extra):
        prod = {'referencia': self.ref.pk, 'costo': '10', 'cantidad': cantidad, **extra}
        if linea is not None:
            prod['detalle_pedido'] = linea
        return self.c.post('/api/suministros/facturas/', {
            'id_manual': id_manual, 'proveedor': self.prov.pk, 'valor': str(10 * cantidad), 'productos': [prod],
        }, format='json')

    def test_recibir_dos_de_tres_deja_uno_pendiente(self):
        r = self.facturar('F1', 2, self.linea.pk)
        self.assertEqual(r.status_code, 201, r.data)
        unidades = Inventario.objects.filter(detalle_pedido=self.linea)
        self.assertEqual(unidades.count(), 2)
        # La venta y la orden se heredan de la línea; la unidad queda para el cliente.
        self.assertTrue(all(u.venta_id == self.venta_a.pk and u.pedido_id == self.orden.pk
                            and u.disponibilidad == 'cliente' for u in unidades))
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, 'pendiente')
        detalle = self.c.get(f'/api/ordenes-pedido/{self.orden.pk}/completo/').data['detalles'][0]
        self.assertEqual((detalle['cantidad'], detalle['recibidas']), (3, 2))

        self.assertEqual(self.facturar('F2', 1, self.linea.pk).status_code, 201)
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, 'recibido')
        self.assertTrue(RegistroAuditoria.objects.filter(accion='orden_pedido.recibida', objeto_id=str(self.orden.pk)).exists())
        # Facturar no duplica: 3 unidades en total, las de las dos facturas.
        self.assertEqual(Inventario.objects.filter(referencia=self.ref).count(), 3)

    def test_no_se_recibe_mas_de_lo_pedido(self):
        self.assertEqual(self.facturar('F1', 2, self.linea.pk).status_code, 201)
        r = self.facturar('F2', 2, self.linea.pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn('pide 3', str(r.data))
        self.assertFalse(FacturaProveedor.objects.filter(id_manual='F2').exists())
        self.assertEqual(Inventario.objects.filter(detalle_pedido=self.linea).count(), 2)

    def test_linea_invalida(self):
        otro = self.proveedor('Proveedor ficticio B')
        ajena = DetallePedido.objects.create(
            orden=OrdenPedido.objects.create(proveedor=otro, usuario=self.admin, fecha_esperada=date.today()),
            referencia=self.referencia(otro, 'De B'), cantidad=1, especificaciones='-')
        self.assertEqual(self.facturar('X1', 1, ajena.pk).status_code, 400)
        otra_venta = self.venta(self.admin)
        r = self.facturar('X2', 1, self.linea.pk, venta=otra_venta.pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn('venta', r.data['productos']['producto_1'])
        self.orden.estado = 'anulado'
        self.orden.save()
        self.assertEqual(self.facturar('X3', 1, self.linea.pk).status_code, 400)
        self.assertFalse(Inventario.objects.exists())

    def test_edicion_respeta_el_tope_y_libera_al_quitar(self):
        r = self.facturar('F1', 3, self.linea.pk)
        factura = FacturaProveedor.objects.get(pk=r.data['id'])
        ids = list(factura.items_inventario.values_list('pk', flat=True))
        base = {'referencia': self.ref.pk, 'costo': '10', 'detalle_pedido': self.linea.pk}
        r = self.c.patch(f'/api/suministros/facturas/{factura.pk}/', {
            'valor': '40', 'productos': [{**base, 'id_referencias': ids, 'cantidad': 4}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(factura.items_inventario.count(), 3)
        r = self.c.patch(f'/api/suministros/facturas/{factura.pk}/', {
            'valor': '20', 'productos': [{**base, 'id_referencias': ids[:2], 'cantidad': 2}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.linea.unidades_recibidas.count(), 2)
        # La orden ya estaba recibida: quitar una unidad no la devuelve sola a pendiente.
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, 'recibido')

    def test_linea_con_recibidas_no_baja_de_ellas(self):
        self.facturar('F1', 2, self.linea.pk)
        r = self.c.patch(f'/api/detalles-pedido/{self.linea.pk}/', {'cantidad': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.delete(f'/api/detalles-pedido/{self.linea.pk}/').status_code, 409)

    def test_rechazo_al_recibir_deja_la_linea_pendiente(self):
        self.facturar('F1', 2, self.linea.pk)
        url = f'/api/detalles-pedido/{self.linea.pk}/rechazos/'
        self.assertEqual(self.c.post(url, {'cantidad': 1}, format='json').status_code, 400)
        self.assertEqual(self.c.post(url, {'cantidad': 2, 'motivo': 'Golpeado'}, format='json').status_code, 400)
        r = self.c.post(url, {'cantidad': 1, 'motivo': 'Llegó golpeado'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data[0]['usuario'], 'admin')
        self.c.post(url, {'cantidad': 1, 'motivo': 'La reposición también llegó mal'}, format='json')
        # Recibidas y rechazadas no se multiplican entre sí; lo pendiente sigue abierto.
        detalle = self.c.get(f'/api/ordenes-pedido/{self.orden.pk}/completo/').data['detalles'][0]
        self.assertEqual((detalle['recibidas'], detalle['rechazadas']), (2, 2))
        filas = self.c.get(f'/api/pedidos/{self.orden.pk}/detalles/').data
        filas = filas.get('detalles', filas) if isinstance(filas, dict) else filas
        self.assertEqual((filas[0]['recibidas'], filas[0]['rechazadas']), (2, 2))
        self.assertTrue(RegistroAuditoria.objects.filter(accion='recepcion.rechazo').exists())
        self.assertEqual(self.facturar('F2', 1, self.linea.pk).status_code, 201)
        # Sin CREAR_FACTURA no se registra.
        vend = self.crear_usuario('vend')
        self.permisos('vendedor', ['VER_ORDENES', 'VER_TODAS_ORDENES'])
        self.assertEqual(self.api(vend).post(url, {'cantidad': 1, 'motivo': 'x'}, format='json').status_code, 403)

    def test_sin_linea_se_comporta_como_antes(self):
        r = self.facturar('F1', 2)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(Inventario.objects.exclude(detalle_pedido=None).exists())

    def test_remision_sugiere_por_unidades_ligadas(self):
        self.facturar('F1', 3, self.linea.pk)
        datos = self.c.get(f'/api/suministros/remisiones/datos-ventas/?ids={self.venta_a.pk}').data[0]
        linea = datos['pedidos'][0]
        self.assertTrue(linea['en_inventario'])
        self.assertEqual(linea['recibidas'], 3)
        self.assertEqual(len(datos['inventario']), 3)
        self.assertEqual(linea['cantidad_por_remisionar'], 0)

    def test_remision_parcialmente_recibida_sugiere_solo_el_resto(self):
        self.facturar('F1', 1, self.linea.pk)
        linea = self.c.get(f'/api/suministros/remisiones/datos-ventas/?ids={self.venta_a.pk}').data[0]['pedidos'][0]
        self.assertFalse(linea['en_inventario'])
        self.assertEqual((linea['recibidas'], linea['cantidad_por_remisionar']), (1, 2))


class EntregaParcialTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.c = self.api(self.admin)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)
        self.venta_a = self.venta(self.admin)
        self.orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=self.venta_a,
                                                fecha_esperada=date.today())
        self.linea = DetallePedido.objects.create(orden=self.orden, referencia=self.ref, cantidad=3, especificaciones='Sillas')
        self.u1 = Inventario.objects.create(id_referencia='U1', referencia=self.ref, venta=self.venta_a, disponibilidad='cliente')
        self.u2 = Inventario.objects.create(id_referencia='U2', referencia=self.ref, venta=self.venta_a, disponibilidad='cliente')
        r = self.c.post('/api/suministros/remisiones/', {
            'ventas': [self.venta_a.pk], 'fecha_entrega': str(date.today()), 'inventario_items': ['U1', 'U2'],
            'items_manuales': [{'referencia': 'Silla', 'cantidad': 3, 'venta': self.venta_a.pk, 'detalle_pedido': self.linea.pk}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.rem = RemisionSuministro.objects.get(pk=r.data['id'])
        self.manual = RemisionItemManual.objects.get(remision=self.rem)
        self.c.patch(f'/api/suministros/remisiones/{self.rem.pk}/', {'estado': 'despachada'}, format='json')

    def confirmar(self, no_entregados, cliente=None, **extra):
        return (cliente or self.c).patch(f'/api/suministros/remisiones/{self.rem.pk}/', {
            'estado': 'finalizada', 'no_entregados': no_entregados, **extra}, format='json')

    def test_entrega_parcial_conserva_pendientes_y_motivo(self):
        r = self.confirmar([
            {'inventario': 'U2', 'motivo': 'rechazado'},
            {'item_manual': self.manual.pk, 'cantidad': 1, 'motivo': 'faltante'},
        ], cerrar_ventas=[self.venta_a.pk])
        self.assertEqual(r.status_code, 200, r.data)
        self.u1.refresh_from_db()
        self.u2.refresh_from_db()
        self.assertEqual((self.u1.disponibilidad, self.u2.disponibilidad), ('entregado', 'cliente'))
        self.assertEqual(NovedadEntrega.objects.filter(remision=self.rem).count(), 2)
        self.assertEqual(len(r.data['no_entregados']), 2)
        evento = self.rem.eventos.get(tipo='finalizada')
        self.assertIn('No entregado', evento.detalle)
        self.assertEqual(evento.usuario, self.admin)
        # Con pendientes la venta no se cierra aunque se pida.
        self.venta_a.refresh_from_db()
        self.assertEqual(self.venta_a.estado, 'pendiente')

        datos = self.c.get(f'/api/suministros/remisiones/datos-ventas/?ids={self.venta_a.pk}').data[0]
        linea = datos['pedidos'][0]
        self.assertIsNone(linea['remision_previa'])
        self.assertEqual(linea['cantidad_por_remisionar'], 1)
        u2 = next(i for i in datos['inventario'] if i['id_referencia'] == 'U2')
        self.assertTrue(u2['seleccionable'])
        # Lo no entregado va en otra remisión.
        r = self.c.post('/api/suministros/remisiones/', {
            'ventas': [self.venta_a.pk], 'fecha_entrega': str(date.today()), 'inventario_items': ['U2']}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_reintento_de_la_confirmacion_no_duplica(self):
        datos = [{'inventario': 'U2', 'motivo': 'rechazado'}]
        self.assertEqual(self.confirmar(datos).status_code, 200)
        r = self.confirmar(datos)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(NovedadEntrega.objects.filter(remision=self.rem).count(), 1)
        self.assertEqual(self.rem.eventos.filter(tipo='finalizada').count(), 1)

    def test_nada_entregado_es_devolucion(self):
        r = self.confirmar([
            {'inventario': 'U1', 'motivo': 'rechazado'}, {'inventario': 'U2', 'motivo': 'rechazado'},
            {'item_manual': self.manual.pk, 'motivo': 'rechazado'},
        ])
        self.assertEqual(r.status_code, 400)
        self.rem.refresh_from_db()
        self.assertEqual(self.rem.estado, 'despachada')
        self.assertFalse(NovedadEntrega.objects.exists())

    def test_validaciones(self):
        for datos in ([{'inventario': 'NOESTA', 'motivo': 'faltante'}],
                      [{'inventario': 'U1', 'motivo': 'otro'}],
                      [{'inventario': 'U1', 'motivo': 'inventado'}],
                      [{'item_manual': self.manual.pk, 'cantidad': 4, 'motivo': 'faltante'}],
                      [{'inventario': 'U1', 'motivo': 'faltante'}, {'inventario': 'U1', 'motivo': 'faltante'}]):
            self.assertEqual(self.confirmar(datos).status_code, 400, datos)
        r = self.c.patch(f'/api/suministros/remisiones/{self.rem.pk}/', {
            'estado': 'creada', 'no_entregados': [{'inventario': 'U1', 'motivo': 'faltante'}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.rem.refresh_from_db()
        self.assertEqual(self.rem.estado, 'despachada')

    def test_entrega_completa_sin_novedades_como_antes(self):
        r = self.confirmar([])
        self.assertEqual(r.status_code, 200, r.data)
        datos = self.c.get(f'/api/suministros/remisiones/datos-ventas/?ids={self.venta_a.pk}').data[0]
        self.assertEqual(datos['pedidos'][0]['remision_previa'], self.rem.pk)
        self.assertEqual(datos['pedidos'][0]['cantidad_por_remisionar'], 0)

    def test_entrega_completa_cierra_la_venta(self):
        r = self.confirmar([], cerrar_ventas=[self.venta_a.pk])
        self.assertEqual(r.status_code, 200, r.data)
        self.venta_a.refresh_from_db()
        self.assertEqual(self.venta_a.estado, 'entregado')

    def test_transportador_asignado_confirma_con_novedad(self):
        t = self.crear_usuario('trans', role='transportador')
        self.rem.transportador_usuario = t
        self.rem.save()
        r = self.confirmar([{'inventario': 'U2', 'motivo': 'danado', 'detalle': 'Pata rota'}], cliente=self.api(t))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(NovedadEntrega.objects.get().usuario, t)
