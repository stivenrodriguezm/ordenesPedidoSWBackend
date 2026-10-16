"""Movimientos de inventario trazables y disponibilidad protegida (P11-02).

Aceptación del plan: cada cambio de una unidad deja origen/destino/motivo/
documento/actor; una unidad en tránsito no vuelve a estar disponible por un
cambio de etiqueta; devolver al proveedor deja pendiente la reposición."""
from datetime import date

from ordenes.models import DetallePedido, OrdenPedido
from ordenes.tests.utils import LottusTestCase
from suministros.models import HistorialTraslado, Inventario, MovimientoInventario, RemisionSuministro, Sede, Zona


class MovimientosInventarioTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.c = self.api(self.admin)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)
        self.venta_a = self.venta(self.admin)
        sede = Sede.objects.create(nombre='Sede ficticia')
        self.bodega = Zona.objects.create(sede=sede, nombre='Bodega')
        self.piso = Zona.objects.create(sede=sede, nombre='Piso 1')

    def tipos(self, pk):
        return list(MovimientoInventario.objects.filter(item_id=pk).values_list('tipo', flat=True))

    def unidad(self, pk='U1', **extra):
        datos = {'referencia': self.ref, 'venta': self.venta_a, 'disponibilidad': 'cliente', 'zona': self.bodega, **extra}
        return Inventario.objects.create(id_referencia=pk, **datos)

    def remision(self, *pks):
        r = self.c.post('/api/suministros/remisiones/', {
            'ventas': [self.venta_a.pk], 'fecha_entrega': str(date.today()), 'inventario_items': list(pks)}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return RemisionSuministro.objects.get(pk=r.data['id'])

    def test_factura_registra_ingreso_con_documento(self):
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'F1', 'proveedor': self.prov.pk, 'valor': '20',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 2, 'zona': self.bodega.pk}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        movs = MovimientoInventario.objects.filter(tipo='ingreso')
        self.assertEqual(movs.count(), 2)
        m = movs.first()
        self.assertEqual((m.documento, m.usuario, m.despues['zona']), (f'factura:{r.data["id"]}', self.admin, self.bodega.pk))

    def test_factura_no_crea_unidades_en_estado_de_proceso(self):
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'F2', 'proveedor': self.prov.pk, 'valor': '10',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 1, 'disponibilidad': 'despachado'}]}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_ciclo_de_remision_deja_cada_paso(self):
        self.unidad('U1')
        self.unidad('U2')
        rem = self.remision('U1', 'U2')
        url = f'/api/suministros/remisiones/{rem.pk}/'
        self.c.patch(url, {'estado': 'despachada'}, format='json')
        r = self.c.patch(url, {'estado': 'finalizada', 'no_entregados': [{'inventario': 'U2', 'motivo': 'rechazado'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.tipos('U1'), ['reserva', 'despacho', 'entrega'])
        self.assertEqual(self.tipos('U2'), ['reserva', 'despacho', 'liberacion'])
        lib = MovimientoInventario.objects.get(item_id='U2', tipo='liberacion')
        self.assertEqual((lib.antes, lib.despues, lib.documento), ({'disponibilidad': 'despachado'}, {'disponibilidad': 'cliente'}, f'remision:{rem.pk}'))

    def test_en_transito_no_se_reabre_por_edicion(self):
        self.unidad('U1')
        self.remision('U1')
        url = '/api/suministros/inventario/U1/'
        self.assertEqual(self.c.patch(url, {'disponibilidad': 'exhibicion'}, format='json').status_code, 400)
        self.assertEqual(self.c.patch(url, {'venta': None}, format='json').status_code, 400)
        # Lo que no es de la remisión se sigue editando.
        self.assertEqual(self.c.patch(url, {'observacion': 'Rayón leve'}, format='json').status_code, 200)
        self.assertEqual(Inventario.objects.get(pk='U1').disponibilidad, 'por_despachar')

    def test_edicion_manual_registra_y_respeta_estados_de_proceso(self):
        self.unidad('U1')
        url = '/api/suministros/inventario/U1/'
        self.assertEqual(self.c.patch(url, {'disponibilidad': 'despachado'}, format='json').status_code, 400)
        r = self.c.patch(url, {'disponibilidad': 'entregado', 'zona': self.piso.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        m = MovimientoInventario.objects.get(item_id='U1', tipo='edicion')
        self.assertEqual(m.antes, {'disponibilidad': 'cliente', 'zona': self.bodega.pk})
        self.assertEqual(HistorialTraslado.objects.filter(item_inventario_id='U1').count(), 1)

    def test_traslado_registra_movimiento_e_historial(self):
        self.unidad('U1')
        r = self.c.post('/api/suministros/inventario/U1/trasladar/', {'zona_destino': self.piso.pk, 'observacion': 'Exhibir'}, format='json')
        self.assertEqual(r.status_code, 200)
        m = MovimientoInventario.objects.get(item_id='U1', tipo='traslado')
        self.assertEqual((m.antes, m.despues, m.motivo), ({'zona': self.bodega.pk}, {'zona': self.piso.pk}, 'Exhibir'))
        self.assertEqual(HistorialTraslado.objects.get(item_inventario_id='U1').zona_destino, self.piso)
        historial = self.c.get('/api/suministros/inventario/U1/movimientos/').data
        self.assertEqual(historial[0]['tipo'], 'traslado')

    def test_devolucion_al_proveedor_deja_pendiente_la_reposicion(self):
        orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=self.venta_a, fecha_esperada=date.today())
        linea = DetallePedido.objects.create(orden=orden, referencia=self.ref, cantidad=2, especificaciones='-')
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'F1', 'proveedor': self.prov.pk, 'valor': '20',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 2, 'detalle_pedido': linea.pk}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'recibido')
        u1, u2 = Inventario.objects.filter(detalle_pedido=linea).order_by('pk')
        url = f'/api/suministros/inventario/{u1.pk}/devolver-proveedor/'
        self.assertEqual(self.c.post(url, {}, format='json').status_code, 400)
        r = self.c.post(url, {'motivo': 'Llegó con la tela equivocada'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['disponibilidad'], 'devuelto_proveedor')
        self.assertEqual(self.c.post(url, {'motivo': 'otra vez'}, format='json').status_code, 409)
        detalle = self.c.get(f'/api/ordenes-pedido/{orden.pk}/completo/').data['detalles'][0]
        self.assertEqual(detalle['recibidas'], 1)
        # No se reactiva a mano ni se remisiona.
        self.assertEqual(self.c.patch(f'/api/suministros/inventario/{u1.pk}/', {'disponibilidad': 'cliente'}, format='json').status_code, 400)
        datos = self.c.get(f'/api/suministros/remisiones/datos-ventas/?ids={self.venta_a.pk}').data[0]
        self.assertFalse(next(i for i in datos['inventario'] if i['id_referencia'] == u1.pk)['seleccionable'])
        # La reposición cabe en la línea.
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'F2', 'proveedor': self.prov.pk, 'valor': '10',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 1, 'detalle_pedido': linea.pk}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_no_se_devuelve_lo_que_va_en_remision(self):
        self.unidad('U1')
        rem = self.remision('U1')
        r = self.c.post('/api/suministros/inventario/U1/devolver-proveedor/', {'motivo': 'x'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn(str(rem.pk), r.data['error'])

    def test_borrar_unidad_con_movimientos_de_proceso(self):
        self.unidad('LIBRE', venta=None, disponibilidad='exhibicion')
        self.assertEqual(self.c.delete('/api/suministros/inventario/LIBRE/').status_code, 204)
        self.unidad('MOVIDA', venta=None, disponibilidad='exhibicion')
        self.c.post('/api/suministros/inventario/MOVIDA/trasladar/', {'zona_destino': self.piso.pk}, format='json')
        self.assertEqual(self.c.delete('/api/suministros/inventario/MOVIDA/').status_code, 409)
        self.assertTrue(Inventario.objects.filter(pk='MOVIDA').exists())
