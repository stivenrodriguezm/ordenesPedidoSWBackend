"""Regresiones de permisos, usuarios y selectores (H20, H21, H25 · P02-03,
P02-04, P08-02 · anexo A)."""
from ordenes.models import CustomUser, Proveedor, RolePermission
from ordenes.tests.utils import LottusTestCase


class ConfiguracionRolesTests(LottusTestCase):
    def test_viewing_role_configuration_removes_aux_default_permissions(self):
        RolePermission.objects.filter(role='auxiliar').delete()
        admin = self.crear_usuario('admin', role='administrador')
        aux = self.crear_usuario('aux', role='auxiliar')
        antes = self.api(aux).get('/api/caja/').status_code
        filas_antes = RolePermission.objects.count()
        r = self.api(admin).get('/api/role-permissions/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(RolePermission.objects.count(), filas_antes)  # GET sin escrituras
        self.assertEqual(self.api(aux).get('/api/caja/').status_code, antes)

    def test_lista_vacia_deliberada_niega_acceso(self):
        aux = self.crear_usuario('aux', role='auxiliar')
        self.permisos('auxiliar', [])
        self.assertEqual(self.api(aux).get('/api/caja/').status_code, 403)

    def test_user_endpoint_y_api_comparten_permisos_base(self):
        RolePermission.objects.filter(role='auxiliar').delete()
        aux = self.crear_usuario('aux', role='auxiliar')
        perms = set(self.api(aux).get('/api/user/').data['permissions'])
        from ordenes.permissions import permisos_efectivos
        self.assertEqual(perms, permisos_efectivos(aux))
        # La API concede exactamente lo que /user/ anuncia
        self.assertIn('VER_INVENTARIO', perms)
        self.assertEqual(self.api(aux).get('/api/suministros/inventario/').status_code, 200)

    def test_solo_admin_edita_roles(self):
        gestor = self.crear_usuario('gestor', role='marketing')
        self.permisos('marketing', ['ADMINISTRAR_USUARIOS', 'VER_USUARIOS'])
        r = self.api(gestor).patch('/api/role-permissions/1/', {'permissions': ['ALL']}, format='json')
        self.assertEqual(r.status_code, 403)


class AdministracionUsuariosTests(LottusTestCase):
    def setUp(self):
        self.gestor = self.crear_usuario('gestor', role='marketing')
        self.permisos('marketing', ['ADMINISTRAR_USUARIOS', 'VER_USUARIOS'])

    def test_user_manager_can_self_promote_to_admin(self):
        r = self.api(self.gestor).patch(f'/api/usuarios/{self.gestor.pk}/', {'role': 'administrador'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.gestor.refresh_from_db()
        self.assertEqual(self.gestor.role, 'marketing')

    def test_gestor_no_crea_ni_promueve_administradores(self):
        otro = self.crear_usuario('otro', role='vendedor')
        c = self.api(self.gestor)
        self.assertEqual(c.patch(f'/api/usuarios/{otro.pk}/', {'role': 'administrador'}, format='json').status_code, 403)
        r = c.post('/api/usuarios/', {'username': 'nuevo', 'role': 'administrador', 'password': 'Clave-segura-123'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(CustomUser.objects.filter(username='nuevo').exists())

    def test_gestor_no_modifica_administradores(self):
        admin = self.crear_usuario('admin', role='administrador')
        r = self.api(self.gestor).patch(f'/api/usuarios/{admin.pk}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 403)
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)

    def test_gestor_administra_roles_no_privilegiados(self):
        r = self.api(self.gestor).post('/api/usuarios/', {
            'username': 'vend', 'first_name': 'V', 'role': 'vendedor', 'password': 'Clave-segura-123',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_ultimo_administrador_protegido(self):
        admin = self.crear_usuario('admin', role='administrador')
        c = self.api(admin)
        self.assertEqual(c.patch(f'/api/usuarios/{admin.pk}/', {'role': 'vendedor'}, format='json').status_code, 400)
        self.assertEqual(c.patch(f'/api/usuarios/{admin.pk}/', {'is_active': False}, format='json').status_code, 400)
        self.assertEqual(c.delete(f'/api/usuarios/{admin.pk}/').status_code, 400)
        admin.refresh_from_db()
        self.assertEqual(admin.role, 'administrador')
        self.assertTrue(admin.is_active)

    def test_admin_si_puede_promover(self):
        admin = self.crear_usuario('admin', role='administrador')
        otro = self.crear_usuario('otro', role='vendedor')
        r = self.api(admin).patch(f'/api/usuarios/{otro.pk}/', {'role': 'administrador'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_borrar_usuario_desactiva_sin_perder_historia(self):
        admin = self.crear_usuario('admin', role='administrador')
        vend = self.crear_usuario('vend', role='vendedor')
        venta = self.venta(vend)
        r = self.api(admin).delete(f'/api/usuarios/{vend.pk}/')
        self.assertIn(r.status_code, (200, 204))
        vend.refresh_from_db()
        self.assertFalse(vend.is_active)
        venta.refresh_from_db()
        self.assertEqual(venta.vendedor_id, vend.id)


class SelectoresTests(LottusTestCase):
    def test_supplier_choices_silently_truncated(self):
        admin = self.crear_usuario('admin', role='administrador')
        Proveedor.objects.bulk_create([Proveedor(nombre_empresa=f'Proveedor ficticio {i:03d}') for i in range(103)])
        c = self.api(admin)
        vistos = []
        url = '/api/proveedores/?page_size=100'
        while url:
            r = c.get(url)
            self.assertEqual(r.status_code, 200)
            vistos += [p['id'] for p in r.data['results']]
            url = r.data['next']
        self.assertEqual(len(vistos), 103)
        self.assertEqual(len(set(vistos)), 103)  # orden estable, sin repetidos
        r = c.get('/api/proveedores/?search=102')
        self.assertEqual([p['nombre_empresa'] for p in r.data['results']], ['Proveedor ficticio 102'])


class BorradoProtegidoTests(LottusTestCase):
    def test_proveedor_con_historia_no_se_borra(self):
        admin = self.crear_usuario('admin', role='administrador')
        p = self.proveedor()
        self.referencia(p)
        r = self.api(admin).delete(f'/api/proveedores/{p.pk}/')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Proveedor.objects.filter(pk=p.pk).exists())
