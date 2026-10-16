"""Regresiones de inventario y facturas de proveedor (H04, H06, H11, H12, H24,
H33 · P02-02, P04-01, P04-02, P04-04, P04-05, P05-02 · anexo A)."""
from datetime import date
from decimal import Decimal

from ordenes.models import ComprobanteEgreso
from ordenes.tests.utils import LottusTestCase
from suministros.models import (
    Categoria, CostoAdicionalInventario, FacturaProveedor, HistorialTraslado, Inventario,
    ItemInventarioTelaCuero, RemisionSuministro, Subcategoria,
)


class CostosInventarioTests(LottusTestCase):
    def setUp(self):
        self.p1 = self.proveedor()
        self.ref = self.referencia(self.p1)
        self.item = Inventario.objects.create(id_referencia='INVCOST', referencia=self.ref, costo_especifico='765')

    def test_inventory_cost_visible_without_cost_permission(self):
        vendedor = self.crear_usuario('seller')
        self.permisos('vendedor', ['VER_INVENTARIO'])
        c = self.api(vendedor)
        r = c.get('/api/suministros/inventario/INVCOST/')
        self.assertEqual(r.status_code, 200)
        for campo in ('costo_especifico', 'costo_total', 'tela_costo_metro', 'costos_adicionales'):
            self.assertNotIn(campo, r.data)
        for tc in r.data.get('telas_cueros', []):
            self.assertNotIn('costo_unidad', tc)
        listado = c.get('/api/suministros/inventario/')
        filas = listado.data['results'] if isinstance(listado.data, dict) else listado.data
        self.assertTrue(all('costo_especifico' not in f for f in filas))

    def test_costo_visible_con_permiso(self):
        aux = self.crear_usuario('aux', role='auxiliar')
        self.permisos('auxiliar', ['VER_INVENTARIO', 'VER_COSTOS_INVENTARIO'])
        r = self.api(aux).get('/api/suministros/inventario/INVCOST/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(str(r.data['costo_especifico'])), Decimal('765'))

    def test_cost_omits_new_fabric_rows(self):
        """Costo integral: base 100 + 3 × 20 de tela = 160 (Decimal)."""
        from suministros.costos import costo_integral
        item = Inventario.objects.create(id_referencia='INVC2', referencia=self.ref, costo_especifico='100')
        ItemInventarioTelaCuero.objects.create(inventario=item, costo_unidad='20', cantidad='3')
        self.assertEqual(costo_integral(item), Decimal('160.00'))
        admin = self.crear_usuario('admin', role='administrador')
        r = self.api(admin).get('/api/suministros/inventario/INVC2/')
        self.assertEqual(Decimal(str(r.data['costo_total'])), Decimal('160.00'))

    def test_costo_integral_sin_doble_conteo_de_tela_heredada(self):
        """Tela heredada (campos lleva_tela/tela_*) copiada a una fila nueva: se cuenta una sola vez."""
        from suministros.costos import costo_integral
        item = Inventario.objects.create(
            id_referencia='INVC3', referencia=self.ref, costo_especifico='100',
            lleva_tela=True, tela_costo_metro='20', tela_cantidad_metros='3',
        )
        ItemInventarioTelaCuero.objects.create(inventario=item, costo_unidad='20', cantidad='3')
        CostoAdicionalInventario.objects.create(inventario=item, descripcion='Mano de obra', valor='15')
        self.assertEqual(costo_integral(item), Decimal('175.00'))
        solo_heredada = Inventario.objects.create(
            id_referencia='INVC4', referencia=self.ref, costo_especifico='100',
            lleva_tela=True, tela_costo_metro='20', tela_cantidad_metros='3',
        )
        self.assertEqual(costo_integral(solo_heredada), Decimal('160.00'))


class EdicionFacturaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.p1 = self.proveedor('Proveedor ficticio A')
        self.p2 = self.proveedor('Proveedor ficticio B')
        self.ref = self.referencia(self.p1)
        self.c = self.api(self.admin)

    def test_invoice_edit_deletes_stock_identity_and_history(self):
        factura = FacturaProveedor.objects.create(id_manual='f3', proveedor=self.p1, valor='100')
        old = Inventario.objects.create(id_referencia='OLD1', referencia=self.ref, factura=factura,
                                        disponibilidad='por_despachar', costo_especifico='100')
        HistorialTraslado.objects.create(item_inventario=old, usuario=self.admin)
        rem = RemisionSuministro.objects.create(vendedor=self.admin, fecha_entrega=date.today())
        rem.inventario_items.add(old)
        qr = old.qr_uuid
        r = self.c.patch(f'/api/suministros/facturas/{factura.pk}/', {
            'productos': [{'id_referencia': 'OLD1', 'referencia': self.ref.pk, 'cantidad': 1, 'costo': 110}],
            'valor': '110',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        old.refresh_from_db()
        self.assertEqual(old.qr_uuid, qr)
        self.assertEqual(old.costo_especifico, Decimal('110'))
        self.assertEqual(rem.inventario_items.count(), 1)
        self.assertEqual(HistorialTraslado.objects.filter(item_inventario_id='OLD1').count(), 1)

    def test_edicion_no_elimina_reservados_omitidos(self):
        factura = FacturaProveedor.objects.create(id_manual='f4', proveedor=self.p1, valor='100')
        Inventario.objects.create(id_referencia='RES1', referencia=self.ref, factura=factura, disponibilidad='por_despachar')
        r = self.c.patch(f'/api/suministros/facturas/{factura.pk}/', {'productos': [], 'valor': '0'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Inventario.objects.filter(pk='RES1').exists())

    def test_edicion_quita_libre_y_agrega_nuevo(self):
        factura = FacturaProveedor.objects.create(id_manual='f5', proveedor=self.p1, valor='100')
        Inventario.objects.create(id_referencia='LIB1', referencia=self.ref, factura=factura, disponibilidad='exhibicion', costo_especifico='100')
        r = self.c.patch(f'/api/suministros/facturas/{factura.pk}/', {
            'productos': [{'referencia': self.ref.pk, 'cantidad': 2, 'costo': 50}], 'valor': '100',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Inventario.objects.filter(pk='LIB1').exists())
        self.assertEqual(factura.items_inventario.count(), 2)

    def test_invoice_accepts_invalid_product_and_total(self):
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'invalida', 'proveedor': self.p1.pk, 'valor': '999',
            'productos': [{'referencia': 999999, 'costo': '1', 'cantidad': 1}],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('productos', r.data)
        self.assertFalse(FacturaProveedor.objects.filter(id_manual='invalida').exists())

    def test_referencia_de_otro_proveedor_rechazada(self):
        ref_b = self.referencia(self.p2, 'De B')
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'mezcla', 'proveedor': self.p1.pk, 'valor': '10',
            'productos': [{'referencia': ref_b.pk, 'costo': '10', 'cantidad': 1}],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(FacturaProveedor.objects.filter(id_manual='mezcla').exists())

    def test_total_descuadrado_rechazado(self):
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'descuadre', 'proveedor': self.p1.pk, 'valor': '999',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 2}],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(FacturaProveedor.objects.filter(id_manual='descuadre').exists())

    def test_cantidad_y_costo_invalidos(self):
        for prod in ({'referencia': self.ref.pk, 'costo': '10', 'cantidad': 0},
                     {'referencia': self.ref.pk, 'costo': 'abc', 'cantidad': 1},
                     {'referencia': self.ref.pk, 'costo': '-10', 'cantidad': 1}):
            r = self.c.post('/api/suministros/facturas/', {
                'id_manual': 'x', 'proveedor': self.p1.pk, 'valor': '10', 'productos': [prod],
            }, format='json')
            self.assertEqual(r.status_code, 400, prod)
        self.assertFalse(FacturaProveedor.objects.exists())

    def test_subcategoria_de_otra_categoria(self):
        cat_a = Categoria.objects.create(nombre='Salas')
        cat_b = Categoria.objects.create(nombre='Comedores')
        sub_b = Subcategoria.objects.create(categoria=cat_b, nombre='Mesa')
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'cat', 'proveedor': self.p1.pk, 'valor': '10',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 1, 'categoria': cat_a.pk, 'subcategoria': sub_b.pk}],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_factura_valida_crea_unidades(self):
        cat = Categoria.objects.create(nombre='Salas')
        r = self.c.post('/api/suministros/facturas/', {
            'id_manual': 'ok', 'proveedor': self.p1.pk, 'valor': '30',
            'productos': [{'referencia': self.ref.pk, 'costo': '10', 'cantidad': 3, 'categoria': cat.pk}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ids = list(Inventario.objects.values_list('id_referencia', flat=True))
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(i.startswith('SA') for i in ids))

    def test_paid_invoice_delete_bypasses_edit_safeguard(self):
        ce = ComprobanteEgreso.objects.create(id=3001, proveedor=self.p1, valor='100', medio_pago='Efectivo', estado='Pagado')
        factura = FacturaProveedor.objects.create(id_manual='pagada', proveedor=self.p1, valor='100',
                                                  estado='pagada', comprobante_egreso=ce)
        r = self.c.delete(f'/api/suministros/facturas/{factura.pk}/')
        self.assertIn(r.status_code, (400, 405, 409))
        self.assertTrue(FacturaProveedor.objects.filter(pk=factura.pk).exists())

    def test_factura_con_inventario_reservado_no_se_borra(self):
        factura = FacturaProveedor.objects.create(id_manual='res', proveedor=self.p1, valor='100')
        Inventario.objects.create(id_referencia='RES2', referencia=self.ref, factura=factura, disponibilidad='despachado')
        r = self.c.delete(f'/api/suministros/facturas/{factura.pk}/')
        self.assertIn(r.status_code, (400, 409))
        self.assertTrue(FacturaProveedor.objects.filter(pk=factura.pk).exists())


class IdentificadoresTests(LottusTestCase):
    def test_generador_no_se_agota_ni_repite(self):
        from suministros.identificadores import siguiente_id_inventario
        Inventario.objects.bulk_create([Inventario(id_referencia=f'SA{n}') for n in range(1000, 10000)])
        nuevo = siguiente_id_inventario('SA')
        self.assertEqual(nuevo, 'SA10000')
        self.assertFalse(Inventario.objects.filter(pk=nuevo).exists())
        self.assertEqual(siguiente_id_inventario('SA'), 'SA10001')

    def test_salta_codigos_heredados_ocupados(self):
        from suministros.identificadores import siguiente_id_inventario
        Inventario.objects.create(id_referencia='CO1000')
        Inventario.objects.create(id_referencia='CO1002')
        self.assertEqual(siguiente_id_inventario('CO'), 'CO1003')
        self.assertEqual(siguiente_id_inventario('ME'), 'ME1000')


class EscrituraCostosSinPermisoTests(LottusTestCase):
    def test_editar_sin_permiso_de_costos_no_borra_el_costo(self):
        p = self.proveedor()
        item = Inventario.objects.create(id_referencia='KEEP1', referencia=self.referencia(p), costo_especifico='765')
        editor = self.crear_usuario('editor', role='marketing')
        self.permisos('marketing', ['VER_INVENTARIO', 'EDITAR_ITEM_INVENTARIO'])
        r = self.api(editor).patch('/api/suministros/inventario/KEEP1/', {'costo_especifico': 0, 'variacion': 'Gris'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        item.refresh_from_db()
        self.assertEqual(item.costo_especifico, Decimal('765'))
        self.assertEqual(item.variacion, 'Gris')
