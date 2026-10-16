"""Juegos compuestos (comedor = mesa + sillas) y variantes especiales del juego (2026-10-09)."""
from decimal import Decimal

from ordenes.tests.utils import LottusTestCase

from .models import CategoriaLista, CargoVariante, GrupoTela, LineaProducto, Multiplicador, VarianteProducto
from .services import calcular_precio, costo_lista, metraje_total, precios_por_variante, resumen_componentes, usa_tela


class JuegosYEspecialesTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=Decimal('2'), es_general=True)
        self.admin = self.crear_usuario('admin_lista', 'administrador')
        self.c = self.api(self.admin)
        comedores = CategoriaLista.objects.create(nombre='Comedores X', slug='comedores-x')
        self.grupo = GrupoTela.objects.create(nombre='Grupo A', orden=1, precio_por_metro=Decimal('10000'))
        self.linea = LineaProducto.objects.create(nombre='Qatar X', slug='qatar-x')
        self.mesa = VarianteProducto.objects.create(linea=self.linea, categoria=comedores, nombre='Mesa de 6', costo_base=Decimal('500000'))
        self.silla = VarianteProducto.objects.create(linea=self.linea, categoria=comedores, nombre='Silla de comedor',
                                                     costo_base=Decimal('100000'), metraje_tela=Decimal('1'))
        self.juego = VarianteProducto.objects.create(linea=self.linea, categoria=comedores, nombre='Comedor 6 puestos', costo_base=0)

    def armar(self, componentes):
        return self.c.put(f'/api/listaprecios/variantes/{self.juego.pk}/componentes/', {'componentes': componentes}, format='json')

    def test_el_juego_cuesta_la_suma_de_sus_componentes(self):
        r = self.armar([{'variante': self.mesa.pk, 'cantidad': 1}, {'variante': self.silla.pk, 'cantidad': 6}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([c['cantidad'] for c in r.data['componentes']], [1, 6])
        juego = VarianteProducto.objects.get(pk=self.juego.pk)
        # Mesa: 500.000 × 2 = 1.000.000; silla: (100.000 + 1 m × 10.000) × 2 = 220.000 × 6.
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('1000000') + Decimal('220000') * 6)
        self.assertEqual(costo_lista(juego, self.grupo), Decimal('500000') + Decimal('110000') * 6)
        self.assertTrue(usa_tela(juego))
        self.assertEqual(metraje_total(juego), Decimal('6'))
        self.assertEqual(resumen_componentes(juego), '1 Mesa de 6 + 6 Silla de comedor')
        self.assertEqual([p['grupo'] for p in precios_por_variante(juego)], [self.grupo.pk])

    def test_validaciones_de_componentes(self):
        otra = LineaProducto.objects.create(nombre='Otra', slug='otra')
        ajena = VarianteProducto.objects.create(linea=otra, categoria=self.mesa.categoria, nombre='Mesa ajena', costo_base=1)
        self.assertEqual(self.armar([{'variante': ajena.pk, 'cantidad': 1}]).status_code, 400)
        self.assertEqual(self.armar([{'variante': self.juego.pk, 'cantidad': 1}]).status_code, 400)
        self.assertEqual(self.armar([{'variante': self.mesa.pk, 'cantidad': 0}]).status_code, 400)
        self.armar([{'variante': self.mesa.pk, 'cantidad': 1}])
        # Un componente no puede convertirse en juego.
        r = self.c.put(f'/api/listaprecios/variantes/{self.mesa.pk}/componentes/', {'componentes': [{'variante': self.silla.pk, 'cantidad': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.armar([]).status_code, 200)  # vuelve a ser un producto normal
        self.assertEqual(self.juego.componentes.count(), 0)

    def test_variante_especial_se_aplica_como_opcional_con_valor_por_variante(self):
        r = self.c.post('/api/listaprecios/especiales/', {'linea': self.linea.pk, 'nombre': 'Reclinables eléctricos', 'valor': '300000',
                                                           'aplicaciones': [{'variante': self.mesa.pk}, {'variante': self.silla.pk, 'valor': '50000'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cargos = {c.variante_id: c for c in CargoVariante.objects.filter(especial_id=r.data['id'])}
        self.assertEqual((cargos[self.mesa.pk].valor, cargos[self.silla.pk].valor), (Decimal('300000'), Decimal('50000')))
        self.assertTrue(all(c.opcional and c.descripcion == 'Reclinables eléctricos' for c in cargos.values()))
        silla = VarianteProducto.objects.get(pk=self.silla.pk)
        self.assertEqual(calcular_precio(silla, self.grupo, [cargos[self.silla.pk].pk]), (Decimal('110000') + Decimal('50000')) * 2)
        # Renombrar conserva a quién aplica; quitar una variante borra su opcional.
        self.c.patch(f"/api/listaprecios/especiales/{r.data['id']}/", {'nombre': 'Reclinable eléctrico'}, format='json')
        self.assertEqual(CargoVariante.objects.filter(especial_id=r.data['id'], descripcion='Reclinable eléctrico').count(), 2)
        self.c.patch(f"/api/listaprecios/especiales/{r.data['id']}/", {'aplicaciones': [{'variante': self.mesa.pk, 'valor': '1'}]}, format='json')
        self.assertEqual(list(CargoVariante.objects.filter(especial_id=r.data['id']).values_list('variante_id', flat=True)), [self.mesa.pk])
        linea = self.c.get(f'/api/listaprecios/lineas/{self.linea.pk}/').data
        self.assertEqual(linea['especiales'][0]['aplicaciones'][0]['variante'], self.mesa.pk)
        self.c.delete(f"/api/listaprecios/especiales/{r.data['id']}/")
        self.assertFalse(CargoVariante.objects.filter(descripcion='Reclinable eléctrico').exists())

    def test_en_ventas_el_juego_es_un_solo_producto(self):
        self.armar([{'variante': self.mesa.pk, 'cantidad': 1}, {'variante': self.silla.pk, 'cantidad': 6}])
        r = self.c.get('/api/productos-venta/catalogo/', {'id': self.juego.pk})
        self.assertEqual(r.status_code, 200, r.data)
        item = r.data['results'][0]
        self.assertEqual(item['juego'], '1 Mesa de 6 + 6 Silla de comedor')
        self.assertTrue(item['tela'])
        self.assertEqual(Decimal(item['metraje']), Decimal('6'))
