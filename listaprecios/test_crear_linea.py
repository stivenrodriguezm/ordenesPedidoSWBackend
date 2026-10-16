"""La configuración comercial se crea sobre referencias existentes."""
from ordenes.tests.utils import LottusTestCase
from .models import LineaProducto, Multiplicador


class CrearLineaTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General creación', valor='1.76', es_general=True)
        self.c = self.api(self.crear_usuario('admin_crear_linea', 'administrador'))
        self.ref = self.referencia(self.proveedor(), 'Sofá Álamo')
        self.url = '/api/listaprecios/lineas/'

    def test_crea_configuracion_de_referencia_sin_copiar_su_identidad(self):
        r = self.c.post(self.url, {'referencia': self.ref.pk, 'notas': 'Colección de sala'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['nombre'], self.ref.nombre)
        self.assertFalse(r.data['activo'])
        self.assertEqual(r.data['variantes'], [])
        self.assertEqual(LineaProducto.objects.get(pk=r.data['id']).referencia_id, self.ref.pk)

    def test_misma_referencia_no_admite_dos_listas(self):
        a = self.c.post(self.url, {'referencia': self.ref.pk}, format='json')
        b = self.c.post(self.url, {'referencia': self.ref.pk}, format='json')
        self.assertEqual((a.status_code, b.status_code), (201, 400), (a.data, b.data))

    def test_crear_producto_independiente_sin_referencia_se_rechaza(self):
        r = self.c.post(self.url, {'nombre': 'Colección independiente'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('referencia', r.data)

    def test_nombre_y_proveedor_se_administran_en_referencias(self):
        creado = self.c.post(self.url, {'referencia': self.ref.pk}, format='json')
        r = self.c.patch(f"{self.url}{creado.data['id']}/", {'nombre': 'Otro nombre'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.nombre, 'Sofá Álamo')
