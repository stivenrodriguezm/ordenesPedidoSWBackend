"""La consulta no devuelve un precio parcial para una combinación inválida."""
from decimal import Decimal

from ordenes.tests.utils import LottusTestCase
from .models import CargoVariante, CategoriaLista, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto


class ConsultaShowroomTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General showroom', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('consulta', 'administrador'))
        self.categoria = CategoriaLista.objects.create(nombre='Salas consulta', slug='salas-consulta')
        self.linea = LineaProducto.objects.create(nombre='Sofá consulta', slug='sofa-consulta')
        self.variante = VarianteProducto.objects.create(linea=self.linea, categoria=self.categoria, nombre='235 cm', costo_base=1000000, metraje_tela=10)
        self.vincular_subcategorias_catalogo(self.linea)
        self.variante.refresh_from_db()
        self.grupo = GrupoTela.objects.create(nombre='Grupo consulta', precio_por_metro=30000)
        self.url = f'/api/listaprecios/variantes/{self.variante.pk}/precio/'

    def test_tapizado_exige_grupo_y_rechaza_parametros_invalidos(self):
        for params in ({}, {'grupo': 'no-numero'}, {'grupo': 999999}, {'grupo': self.grupo.pk, 'opcionales': 'a,b'}):
            with self.subTest(params=params):
                self.assertEqual(self.c.get(self.url, params).status_code, 400)
        res = self.c.get(self.url, {'grupo': self.grupo.pk})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(str(res.data['precio'])), Decimal('2600000'))

    def test_rechaza_grupo_no_ofrecido_y_adicional_ajeno(self):
        otro = GrupoTela.objects.create(nombre='Otro consulta', precio_por_metro=40000)
        PrecioVariante.objects.create(variante=self.variante, grupo=self.grupo, precio_manual=3000000)
        self.assertEqual(self.c.get(self.url, {'grupo': otro.pk}).status_code, 400)
        self.assertEqual(self.c.get(self.url, {'grupo': self.grupo.pk, 'opcionales': '999999'}).status_code, 400)
        extra = CargoVariante.objects.create(variante=self.variante, descripcion='Reclino', valor=100000, opcional=True)
        res = self.c.get(self.url, {'grupo': self.grupo.pk, 'opcionales': str(extra.pk)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(str(res.data['precio'])), Decimal('3200000'))
        self.assertEqual(res.data['opcionales_incluidos'][0]['id'], extra.pk)
        self.assertEqual(res.data['opcionales_incluidos'][0]['valor'], Decimal('200000'))

    def test_precio_unico_no_admite_tela_y_subcategoria_sin_publicar_no_se_cotiza(self):
        self.variante.metraje_tela = None
        self.variante.save()
        self.assertEqual(self.c.get(self.url).status_code, 200)
        self.assertEqual(self.c.get(self.url, {'grupo': self.grupo.pk}).status_code, 400)
        self.variante.publicado = False
        self.variante.save()
        self.assertEqual(self.c.get(self.url).status_code, 404)

    def test_consulta_exige_permiso(self):
        self.permisos('vendedor', [])
        self.c = self.api(self.crear_usuario('sin_consulta', 'vendedor'))
        self.assertEqual(self.c.get(self.url, {'grupo': self.grupo.pk}).status_code, 403)
