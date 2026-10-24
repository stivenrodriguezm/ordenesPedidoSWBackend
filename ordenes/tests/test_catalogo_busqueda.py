"""Buscador de productos en la venta (2026-10-24): la respuesta queda en la caché del catálogo
(sin volver a la base remota) y se descarta en cuanto cambia la lista de precios."""
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from listaprecios.models import VarianteProducto
from ordenes.tests import test_productos_venta as base
from ordenes.tests.utils import LottusTestCase
from suministros.models import Subcategoria


class BuscadorCatalogoTests(LottusTestCase):
    def setUp(self):
        base.ProductosVentaTests.setUp(self)
        cache.clear()
        self.vincular_subcategorias_catalogo(self.variante.linea)
        self.variante.refresh_from_db()

    def buscar(self, q=''):
        r = self.api_asesor.get('/api/productos-venta/catalogo/', {'q': q})
        self.assertEqual(r.status_code, 200)
        return [p['id'] for p in r.data['results']]

    def test_la_segunda_busqueda_sale_de_la_cache(self):
        self.assertEqual(self.buscar('tres'), [self.variante.pk])
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.buscar('  TRES '), [self.variante.pk])  # mayúsculas y espacios: misma búsqueda
        tablas = ' '.join(x['sql'] for x in ctx.captured_queries)
        self.assertNotIn('listaprecios_variante_producto', tablas)

    def test_un_cambio_en_la_lista_se_ve_en_la_siguiente_busqueda(self):
        self.assertEqual(self.buscar('tres'), [self.variante.pk])
        with self.captureOnCommitCallbacks(execute=True):
            Subcategoria.objects.filter(pk=self.variante.subcategoria_id).update(nombre='Dos puestos')
            # update() no dispara señales; un guardado normal de la lista sí invalida.
            VarianteProducto.objects.get(pk=self.variante.pk).save()
        self.assertEqual(self.buscar('tres'), [])
        self.assertEqual(self.buscar('dos'), [self.variante.pk])

    def test_sin_permiso_no_se_sirve_desde_la_cache(self):
        self.buscar('tres')
        otro = self.api(self.crear_usuario('sin_precios', role='marketing'))
        self.assertEqual(otro.get('/api/productos-venta/catalogo/', {'q': 'tres'}).status_code, 403)
