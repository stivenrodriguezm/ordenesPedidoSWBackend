from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from ordenes.tests.utils import LottusTestCase
from .models import CategoriaLista, GrupoTela, LineaProducto, Multiplicador, VarianteProducto, PrecioVariante
from .services import calcular_precio, costo_lista, guardar_componentes, precios_por_variante


class CapturaAdminTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General captura', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_captura', 'administrador'))
        self.cat = CategoriaLista.objects.create(nombre='Sala captura', slug='sala-captura')
        self.linea = LineaProducto.objects.create(nombre='Detroit captura', slug='detroit-captura')
        self.tela = GrupoTela.objects.create(nombre='Tela captura', tipo='tela', precio_por_metro=30000)
        self.cuero = GrupoTela.objects.create(nombre='Cuero captura', tipo='cuero', precio_por_metro=1000)
        self.v = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Sofá 235', costo_base=1000000,
                                                 metraje_tela=10, decimetraje_cuero=120)
        self.url = f'/api/listaprecios/variantes/{self.v.pk}/'

    def test_tela_y_cuero_usan_consumos_independientes_en_precio_y_costo(self):
        self.assertEqual(calcular_precio(self.v, self.tela), Decimal('2600000'))
        self.assertEqual(calcular_precio(self.v, self.cuero), Decimal('2240000'))
        self.assertEqual(costo_lista(self.v, self.cuero), Decimal('1120000'))
        res = self.c.patch(self.url, {'decimetraje_cuero': '150.50'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.v.refresh_from_db()
        self.assertEqual(calcular_precio(self.v, self.tela), Decimal('2600000'))
        self.assertEqual(calcular_precio(self.v, self.cuero), Decimal('2301000'))
        self.assertIn('precios_venta', res.data)

    def test_no_ofrece_grupos_del_material_desactivado_ni_un_precio_parcial(self):
        res = self.c.patch(self.url, {'metraje_tela': None}, format='json')
        self.assertEqual(res.status_code, 200)
        self.v.refresh_from_db()
        self.assertEqual([p['grupo'] for p in precios_por_variante(self.v)], [self.cuero.pk])
        url = f'/api/listaprecios/variantes/{self.v.pk}/precio/'
        self.assertEqual(self.c.get(url, {'grupo': self.tela.pk}).status_code, 400)
        self.assertEqual(self.c.get(url, {'grupo': self.cuero.pk}).status_code, 200)

    def test_rechaza_costos_con_centavos_negativos_porcentajes_y_consumos_invalidos(self):
        for campo, valor in [('costo_base', '10.50'), ('costo_base', '-1'), ('descuento_maximo', '100.01'),
                             ('descuento_maximo', '-1'), ('metraje_tela', '0'), ('decimetraje_cuero', '-1'), ('decimetraje_cuero', '1.234')]:
            with self.subTest(campo=campo, valor=valor):
                r = self.c.patch(self.url, {campo: valor}, format='json')
                self.assertEqual(r.status_code, 400, r.data)
        self.v.refresh_from_db()
        self.assertEqual(self.v.costo_base, Decimal('1000000'))
        self.assertEqual(self.v.decimetraje_cuero, Decimal('120'))

    def test_tope_cero_no_se_confunde_con_tope_por_defecto(self):
        self.assertEqual(self.c.patch(self.url, {'descuento_maximo': '0'}, format='json').status_code, 200)
        self.v.refresh_from_db()
        self.assertEqual(self.v.descuento_maximo, 0)
        self.assertEqual(self.c.patch(self.url, {'descuento_maximo': None}, format='json').status_code, 200)
        self.v.refresh_from_db()
        self.assertIsNone(self.v.descuento_maximo)

    def test_juego_suma_el_decimetraje_de_sus_piezas_y_excluye_material_no_ofrecido(self):
        mesa = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Mesa', costo_base=500000)
        juego = VarianteProducto.objects.create(linea=self.linea, categoria=self.cat, nombre='Conjunto', costo_base=0)
        guardar_componentes(juego, [{'variante': mesa.pk, 'cantidad': 1}, {'variante': self.v.pk, 'cantidad': 2}])
        self.assertEqual(calcular_precio(juego, self.cuero), Decimal('5480000'))
        self.assertEqual(costo_lista(juego, self.cuero), Decimal('2740000'))
        self.v.decimetraje_cuero = None
        self.v.save()
        juego = VarianteProducto.objects.get(pk=juego.pk)
        self.assertEqual([p['grupo'] for p in precios_por_variante(juego)], [self.tela.pk])

    def test_conserva_precio_manual_sin_consumo_de_ese_material(self):
        self.v.decimetraje_cuero = None
        self.v.save()
        PrecioVariante.objects.create(variante=self.v, grupo=self.cuero, precio_manual=4000000)
        self.assertEqual(precios_por_variante(self.v)[0]['precio'], Decimal('4000000'))

    def test_migracion_preserva_el_calculo_anterior_sin_convertir_unidades(self):
        self.v.decimetraje_cuero = None
        self.v.save()
        # Ejecuta el paso de datos real sobre filas que representan el esquema anterior.
        import_module('listaprecios.migrations.0014_consumo_cuero_independiente').conservar_consumos_existentes(
            apps, SimpleNamespace(connection=connection))
        self.v.refresh_from_db()
        self.assertEqual(self.v.decimetraje_cuero, self.v.metraje_tela)
        anterior = (self.v.costo_base + self.v.metraje_tela * self.cuero.precio_por_metro) * 2
        self.assertEqual(calcular_precio(self.v, self.cuero), anterior)

    def test_catalogo_de_ventas_admite_producto_que_solo_lleva_cuero(self):
        self.v.metraje_tela = None
        self.v.save()
        r = self.c.get('/api/productos-venta/catalogo/', {'id': self.v.pk})
        self.assertEqual(r.status_code, 200, r.data)
        item = r.data['results'][0]
        self.assertTrue(item['tela'])
        self.assertIsNone(item['metraje'])
        self.assertEqual(Decimal(item['decimetraje_cuero']), Decimal('120'))
        self.assertEqual(item['grupos'], [self.cuero.pk])
