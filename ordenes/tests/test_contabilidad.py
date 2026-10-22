"""Rol Contabilidad y venta facturada (2026-10-21): ve ventas, recibos y comprobantes; solo
marca ventas como facturadas. No cambia nada para quien no tiene MARCAR_VENTA_FACTURADA."""
from ordenes.models import RegistroAuditoria, RolePermission, Venta
from ordenes.tests.utils import LottusTestCase


class ContabilidadTests(LottusTestCase):
    def setUp(self):
        self.vendedor = self.crear_usuario('vendedor_fact')
        self.conta = self.crear_usuario('conta', 'contabilidad', first_name='Ana', last_name='Contable')
        self.api_conta = self.api(self.conta)
        self.venta_a = self.venta(self.vendedor, '500000')

    def test_el_rol_trae_sus_permisos_por_defecto(self):
        rp = RolePermission.objects.get(role='contabilidad')
        self.assertIn('MARCAR_VENTA_FACTURADA', rp.permissions)
        self.assertNotIn('CREAR_VENTA', rp.permissions)
        datos = self.api_conta.get('/api/user/').data
        self.assertEqual(datos['role'], 'contabilidad')

    def test_ve_ventas_recibos_y_comprobantes_pero_no_crea(self):
        self.assertEqual(self.api_conta.get('/api/ventas/').status_code, 200)
        self.assertEqual(self.api_conta.get('/api/recibos-caja/').status_code, 200)
        self.assertEqual(self.api_conta.get('/api/comprobantes-egreso/').status_code, 200)
        self.assertEqual(self.api_conta.post('/api/recibos-caja/crear/', {}, format='json').status_code, 403)
        self.assertEqual(self.api_conta.post('/api/comprobantes-egreso/crear/', {}, format='json').status_code, 403)
        self.assertEqual(self.api_conta.put(f'/api/ventas/{self.venta_a.pk}/editar/', {}, format='json').status_code, 403)
        self.assertEqual(self.api_conta.post('/api/ventas/crear/', {}, format='json').status_code, 403)

    def test_marca_y_desmarca_facturada_con_quien_y_cuando(self):
        url = f'/api/ventas/{self.venta_a.pk}/facturada/'
        r = self.api_conta.post(url, {'facturada': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['facturada'], r.data['facturada_por_nombre']), (True, 'Ana Contable'))
        v = Venta.objects.get(pk=self.venta_a.pk)
        self.assertTrue(v.facturada and v.facturada_en and v.facturada_por_id == self.conta.pk)
        fila = next(x for x in self.api_conta.get('/api/ventas/').data if x['id'] == v.pk)
        self.assertEqual((fila['facturada'], fila['facturada_por_nombre']), (True, 'Ana Contable'))
        self.assertTrue(RegistroAuditoria.objects.filter(accion='venta.facturada', objeto_id=str(v.pk)).exists())
        r = self.api_conta.post(url, {'facturada': False}, format='json')
        self.assertEqual((r.status_code, r.data['facturada']), (200, False))
        v.refresh_from_db()
        self.assertIsNone(v.facturada_en)
        self.assertEqual(self.api_conta.post(url, {'facturada': 'si'}, format='json').status_code, 400)

    def test_sin_el_permiso_no_puede_marcar_y_una_anulada_no_se_factura(self):
        url = f'/api/ventas/{self.venta_a.pk}/facturada/'
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS', 'CREAR_VENTA'])
        self.assertEqual(self.api(self.vendedor).post(url, {'facturada': True}, format='json').status_code, 403)
        anulada = self.venta(self.vendedor, '1000', estado=Venta.ESTADO_ANULADA)
        r = self.api_conta.post(f'/api/ventas/{anulada.pk}/facturada/', {'facturada': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api_conta.post('/api/ventas/999999/facturada/', {'facturada': True}, format='json').status_code, 404)

    def test_editar_la_venta_no_cambia_la_facturacion(self):
        Venta.objects.filter(pk=self.venta_a.pk).update(facturada=True)
        admin = self.api(self.crear_usuario('admin_fact', 'administrador'))
        r = admin.patch(f'/api/ventas/{self.venta_a.pk}/editar/', {'facturada': False, 'observacion': ''}, format='json')
        self.assertTrue(Venta.objects.get(pk=self.venta_a.pk).facturada)
