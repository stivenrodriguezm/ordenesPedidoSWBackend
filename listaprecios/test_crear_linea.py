"""Creación de colecciones con el mismo payload del formulario administrativo."""
from decimal import Decimal

from ordenes.tests.utils import LottusTestCase
from .models import LineaProducto, Multiplicador


class CrearLineaTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General creación', valor=Decimal('1.76'), es_general=True)
        self.c = self.api(self.crear_usuario('admin_crear_linea', 'administrador'))
        self.url = '/api/listaprecios/lineas/'

    def test_formulario_crea_linea_sin_exigir_slug(self):
        payload = {'nombre': 'Sofá Álamo', 'notas': 'Colección de sala', 'activo': True, 'fotos': []}
        r = self.c.post(self.url, payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['slug'], 'sofa-alamo')
        self.assertEqual(r.data['variantes'], [])
        self.assertTrue(LineaProducto.objects.filter(pk=r.data['id'], nombre=payload['nombre']).exists())

    def test_nombres_repetidos_reciben_identificadores_distintos(self):
        a = self.c.post(self.url, {'nombre': 'Línea nueva'}, format='json')
        b = self.c.post(self.url, {'nombre': 'Línea nueva'}, format='json')
        self.assertEqual((a.status_code, b.status_code), (201, 201), (a.data, b.data))
        self.assertNotEqual(a.data['slug'], b.data['slug'])

    def test_slug_vacio_se_genera_y_nombre_vacio_se_rechaza(self):
        valido = self.c.post(self.url, {'nombre': 'Colección', 'slug': ''}, format='json')
        self.assertEqual(valido.status_code, 201, valido.data)
        invalido = self.c.post(self.url, {'nombre': '  '}, format='json')
        self.assertEqual(invalido.status_code, 400)
        self.assertIn('nombre', invalido.data)

    def test_editar_nombre_no_cambia_identificador_existente(self):
        linea = LineaProducto.objects.create(nombre='Original', slug='original')
        r = self.c.patch(f'{self.url}{linea.pk}/', {'nombre': 'Nombre actualizado'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['slug'], 'original')
