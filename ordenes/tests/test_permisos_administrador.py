"""El administrador obedece los permisos de su rol (2026-10-24): lo que se apaga en
Gestión de usuarios deja de verse y de funcionar también para él. Solo conserva siempre
Gestión de usuarios, para poder corregir la configuración."""
from django.utils import timezone

from ordenes.permissions import ADMIN_SIEMPRE, permisos_efectivos
from ordenes.models import RolePermission
from ordenes.tests.utils import LottusTestCase
from suministros.models import FacturaProveedor, Inventario


class AdministradorSigueSuRolTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin_rol', role='administrador')
        self.c = self.api(self.admin)
        self.venta_a = self.venta(self.crear_usuario('vend_rol'), '500000')

    def test_permiso_apagado_niega_y_encendido_concede(self):
        self.permisos('administrador', ['VER_TODAS_VENTAS'])
        url = f'/api/ventas/{self.venta_a.pk}/facturada/'
        self.assertEqual(self.c.post(url, {'facturada': True}, format='json').status_code, 403)
        self.assertEqual(self.c.get('/api/listaprecios/catalogo/').status_code, 403)
        self.permisos('administrador', ['VER_TODAS_VENTAS', 'MARCAR_VENTA_FACTURADA'])
        self.assertEqual(self.c.post(url, {'facturada': True}, format='json').status_code, 200)

    def test_user_anuncia_la_lista_del_rol_mas_gestion_de_usuarios(self):
        self.permisos('administrador', ['ALL', 'VER_INICIO'])
        perms = set(self.c.get('/api/user/').data['permissions'])
        self.assertEqual(perms, {'VER_INICIO'} | ADMIN_SIEMPRE)  # 'ALL' heredado no cuenta
        self.assertEqual(self.c.get('/api/role-permissions/').status_code, 200)

    def test_sin_configuracion_guardada_conserva_acceso_total(self):
        RolePermission.objects.filter(role='administrador').delete()
        self.assertEqual(permisos_efectivos(self.admin), {'ALL'})

    def test_guardar_el_rol_nunca_quita_gestion_de_usuarios(self):
        rp, _ = RolePermission.objects.get_or_create(role='administrador', defaults={'permissions': []})
        r = self.c.put(f'/api/role-permissions/{rp.pk}/', {'permissions': ['VER_INICIO']}, format='json')
        self.assertEqual(r.status_code, 200)
        rp.refresh_from_db()
        self.assertTrue(ADMIN_SIEMPRE <= set(rp.permissions))


class PermisosQueAntesNoHacianNadaTests(LottusTestCase):
    def setUp(self):
        self.aux = self.crear_usuario('aux_estado', role='auxiliar')
        self.c = self.api(self.aux)
        self.ref = self.referencia(self.proveedor())

    def test_estado_fisico_y_disponibilidad_requieren_su_permiso(self):
        item = Inventario.objects.create(id_referencia='E1', referencia=self.ref, disponibilidad='exhibicion')
        url = f'/api/suministros/inventario/{item.pk}/'
        self.permisos('auxiliar', ['VER_INVENTARIO', 'EDITAR_ITEM_INVENTARIO'])
        self.assertEqual(self.c.patch(url, {'estado_fisico': 'por_reparar'}, format='json').status_code, 403)
        self.assertEqual(self.c.patch(url, {'observacion': 'Sin cambio de estado'}, format='json').status_code, 200)
        self.permisos('auxiliar', ['VER_INVENTARIO', 'EDITAR_ITEM_INVENTARIO', 'EDITAR_ESTADO_ITEM'])
        self.assertEqual(self.c.patch(url, {'estado_fisico': 'por_reparar'}, format='json').status_code, 200)

    def test_fechas_de_factura_requieren_su_permiso(self):
        factura = FacturaProveedor.objects.create(id_manual='F-1', valor=1000, proveedor=self.ref.proveedor,
                                                  fecha_factura=timezone.now())
        url = f'/api/suministros/facturas/{factura.pk}/'
        self.permisos('auxiliar', ['VER_FACTURAS', 'EDITAR_FACTURA'])
        self.assertEqual(self.c.patch(url, {'fecha_pago': '2030-01-31'}, format='json').status_code, 403)
        # Reenviar el mismo día (con otra hora, como hace el formulario) no es un cambio.
        mismo_dia = timezone.localtime(factura.fecha_factura).strftime('%Y-%m-%dT00:00:01')
        self.assertEqual(self.c.patch(url, {'fecha_factura': mismo_dia, 'observaciones': 'x'}, format='json').status_code, 200)
        self.permisos('auxiliar', ['VER_FACTURAS', 'EDITAR_FACTURA', 'EDITAR_FECHAS_FACTURA'])
        self.assertEqual(self.c.patch(url, {'fecha_pago': '2030-01-31'}, format='json').status_code, 200)
