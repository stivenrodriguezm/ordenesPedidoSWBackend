"""La captura de precios no debe consultar la BD por celda ni por pieza."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from ordenes.tests.utils import LottusTestCase
from .models import CategoriaLista, ComponenteJuego, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from .serializers import LineaProductoSerializer
from .views import LineaProductoViewSet, _precios_context


class RendimientoAdminTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.admin = self.crear_usuario('admin_rendimiento', 'administrador')
        self.c = self.api(self.admin)
        self.cat = CategoriaLista.objects.create(nombre='Prueba', slug='rendimiento')
        self.linea = LineaProducto.objects.create(nombre='Colección', slug='rendimiento')
        self.silla = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Silla', costo_base=100000, metraje_tela=1)
        self.juego = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Comedor', costo_base=0)
        ComponenteJuego.objects.create(juego=self.juego, variante=self.silla, cantidad=6)
        for i in range(8):
            grupo = GrupoTela.objects.create(nombre=f'Grupo {i}', precio_por_metro=10000)
            PrecioVariante.objects.create(variante=self.silla, grupo=grupo)
            PrecioVariante.objects.create(variante=self.juego, grupo=grupo)

    def test_serializar_coleccion_con_conjuntos_tiene_consultas_acotadas(self):
        with CaptureQueriesContext(connection) as consultas:
            linea = LineaProductoViewSet.queryset.get(pk=self.linea.pk)
            data = LineaProductoSerializer(linea, context=_precios_context()).data
        self.assertLessEqual(len(consultas), 20, f'{len(consultas)} consultas para solo dos productos')
        juego = next(v for v in data['variantes'] if v['id'] == self.juego.pk)
        self.assertEqual(Decimal(juego['precios_venta'][0]['precio']), Decimal('1320000'))
        VarianteProducto.objects.bulk_create([
            VarianteProducto(linea=self.linea, categoria=self.cat, nombre=f'Silla {i}', costo_base=100000, metraje_tela=1)
            for i in range(25)
        ])
        with CaptureQueriesContext(connection) as ampliadas:
            linea = LineaProductoViewSet.queryset.get(pk=self.linea.pk)
            data = LineaProductoSerializer(linea, context=_precios_context()).data
        self.assertEqual(len(data['variantes']), 27)
        self.assertLessEqual(len(ampliadas), len(consultas) + 1, 'Agregar productos no debe multiplicar las consultas')

    def test_resumen_no_calcula_precios_y_detalle_conserva_contrato(self):
        with CaptureQueriesContext(connection) as consultas:
            r = self.c.get('/api/listaprecios/lineas/?resumen=1')
        self.assertEqual(r.status_code, 200, r.data)
        linea = next(l for l in r.data if l['id'] == self.linea.pk)
        self.assertTrue(linea['resumen'])
        self.assertNotIn('costo_base', linea['variantes'][0])
        self.assertEqual(linea['variantes'][0]['categoria_nombre'], 'Prueba')
        self.assertFalse(any('listaprecios_grupotela' in q['sql'] for q in consultas))
        detalle = self.c.get(f'/api/listaprecios/lineas/{self.linea.pk}/')
        self.assertEqual(detalle.status_code, 200, detalle.data)
        self.assertIn('precios_venta', detalle.data['variantes'][0])

    def test_patch_costo_no_hace_consultas_por_cada_grupo(self):
        with CaptureQueriesContext(connection) as consultas:
            r = self.c.patch(f'/api/listaprecios/variantes/{self.silla.pk}/', {'costo_base': 120000}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertLessEqual(len(consultas), 24, f'{len(consultas)} consultas al guardar un costo')
        self.assertEqual(Decimal(r.data['precios_venta'][0]['precio']), Decimal('260000'))

    def test_resumen_y_detalle_mantienen_permiso_de_costos(self):
        vendedor = self.crear_usuario('lector_rendimiento', 'vendedor')
        self.permisos('vendedor', ['VER_LISTA_PRECIOS'])
        api = self.api(vendedor)
        self.assertEqual(api.get('/api/listaprecios/lineas/?resumen=1').status_code, 403)
        self.assertEqual(api.get(f'/api/listaprecios/lineas/{self.linea.pk}/').status_code, 403)
