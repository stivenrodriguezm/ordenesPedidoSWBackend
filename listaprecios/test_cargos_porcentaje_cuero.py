"""Cargos en % y con tela, «Mostrar en agrupación», máximo de unidades y variación en cuero
(2026-10-27). Todo se suma al costo antes del multiplicador."""
from decimal import Decimal

from django.core.cache import cache

from ordenes.tests.utils import LottusTestCase
from .models import CargoVariante, CategoriaLista, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from .services import calcular_precio, costo_lista, opcionales_de_variante, precios_por_variante, validar_unidades_opcionales


class CargosPorcentajeYCueroTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_cargos_pct', 'administrador'))
        cat = CategoriaLista.objects.create(nombre='Salas pct', slug='salas-pct')
        self.linea = LineaProducto.objects.create(nombre='Sala pct', slug='sala-pct')
        self.sofa = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='Sofá 3', costo_base=1000000,
                                                    metraje_tela=8, decimetraje_cuero=100)
        self.tela = GrupoTela.objects.create(nombre='Grupo pct', tipo='tela', precio_por_metro=10000)
        self.cuero = GrupoTela.objects.create(nombre='Cuero pct', tipo='cuero', precio_por_metro=1000)

    def cargo(self, **datos):
        r = self.c.post('/api/listaprecios/cargos/', {'variante': self.sofa.pk, 'descripcion': 'Cargo', 'valor': 0, **datos}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def patch_cargo(self, cargo, **datos):
        return self.c.patch(f"/api/listaprecios/cargos/{cargo['id']}/", datos, format='json')

    def fresco(self):
        return VarianteProducto.objects.prefetch_related('cargos', 'precios', 'componentes').get(pk=self.sofa.pk)

    def test_cargo_porcentual_sobre_el_costo_base(self):
        self.cargo(descripcion='Armado', valor='15', modo_valor='porcentaje')
        # (1.000.000 + 8 m × 10.000 + 15% de 1.000.000) × 2
        self.assertEqual(calcular_precio(self.fresco(), self.tela), Decimal('2460000'))
        self.assertEqual(costo_lista(self.fresco(), self.tela), Decimal('1230000'))

    def test_cargo_con_tela_se_cobra_con_el_grupo_del_producto(self):
        cargo = self.cargo(descripcion='Faldón', valor=20000, metraje_tela='1.5', decimetraje_cuero='20')
        # Tela: (1.000.000 + 80.000 + 20.000 + 1,5 × 10.000) × 2; cuero: (1.000.000 + 100.000 + 20.000 + 20 × 1.000) × 2
        self.assertEqual(calcular_precio(self.fresco(), self.tela), Decimal('2230000'))
        self.assertEqual(calcular_precio(self.fresco(), self.cuero), Decimal('2280000'))
        # Un opcional con tela ofrece un valor por grupo cuando aún no se elige grupo.
        self.patch_cargo(cargo, opcional=True)
        item = next(o for o in opcionales_de_variante(self.fresco()) if o['id'] == cargo['id'])
        self.assertIsNone(item['valor'])
        self.assertIn({'grupo': self.tela.pk, 'valor': Decimal('70000')}, item['precios'])

    def test_validaciones_del_valor_y_del_modo(self):
        cargo = self.cargo(descripcion='Armado', valor=1000)
        self.assertEqual(self.patch_cargo(cargo, valor='10.5').status_code, 400)  # pesos sin centavos
        r = self.patch_cargo(cargo, modo_valor='porcentaje')
        self.assertEqual((r.status_code, Decimal(r.data['valor'])), (200, Decimal(0)))  # al cambiar de modo, el valor se pide de nuevo
        self.assertEqual(self.patch_cargo(cargo, valor='12.5').status_code, 200)
        self.assertEqual(self.patch_cargo(cargo, valor='1500').status_code, 400)
        transporte = self.cargo(tipo='transporte')
        self.assertEqual(self.patch_cargo(transporte, modo_valor='porcentaje').status_code, 400)
        self.assertEqual(self.patch_cargo(transporte, metraje_tela='1').status_code, 400)
        self.assertEqual(self.patch_cargo(cargo, cantidad_maxima=0).status_code, 400)

    def test_maximo_de_unidades_de_un_opcional(self):
        reclino = self.cargo(descripcion='Reclino', valor=100000, opcional=True, cantidad_maxima=3)
        item = next(o for o in opcionales_de_variante(self.fresco(), grupo=self.tela) if o['id'] == reclino['id'])
        self.assertEqual(item['maximo'], 3)
        validar_unidades_opcionales(self.fresco(), [reclino['id']] * 3)
        with self.assertRaisesMessage(Exception, 'admite hasta 3'):
            validar_unidades_opcionales(self.fresco(), [reclino['id']] * 4)

    def test_variacion_en_cuero_en_pesos_y_en_porcentaje(self):
        url = f'/api/listaprecios/variantes/{self.sofa.pk}/'
        r = self.c.patch(url, {'variacion_cuero_tipo': 'pesos', 'variacion_cuero_valor': 50000}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        # Tela sin cambio; cuero: (1.000.000 + 100 dm × 1.000 + 50.000) × 2
        self.assertEqual(calcular_precio(self.fresco(), self.tela), Decimal('2160000'))
        self.assertEqual(calcular_precio(self.fresco(), self.cuero), Decimal('2300000'))
        r = self.c.patch(url, {'variacion_cuero_tipo': 'porcentaje', 'variacion_cuero_valor': '10'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        # 10% de (1.000.000 + 100.000) = 110.000 de costo más
        self.assertEqual(calcular_precio(self.fresco(), self.cuero), Decimal('2420000'))
        self.assertEqual(self.c.patch(url, {'variacion_cuero_tipo': 'pesos', 'variacion_cuero_valor': '10.5'}, format='json').status_code, 400)
        self.assertEqual(self.c.patch(url, {'variacion_cuero_tipo': ''}, format='json').data['variacion_cuero_valor'], None)

    def test_un_cargo_que_no_se_muestra_en_la_agrupacion_no_se_cobra_ni_se_ofrece_alli(self):
        oculto = self.cargo(descripcion='Instalación', valor=30000, en_agrupacion=False)
        opcional = self.cargo(descripcion='USB', valor=10000, opcional=True, en_agrupacion=False)
        juego = VarianteProducto.objects.create(linea=self.linea, categoria=self.sofa.categoria, nombre='Sala completa', costo_base=0)
        r = self.c.put(f'/api/listaprecios/variantes/{juego.pk}/componentes/', {'componentes': [{'variante': self.sofa.pk, 'cantidad': 1}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        juego = VarianteProducto.objects.prefetch_related('cargos', 'precios', 'componentes__variante__cargos', 'componentes__variante__precios').get(pk=juego.pk)
        # Suelto lleva la instalación; dentro de la sala, no.
        self.assertEqual(calcular_precio(self.fresco(), self.tela), Decimal('2220000'))
        self.assertEqual(calcular_precio(juego, self.tela), Decimal('2160000'))
        self.assertNotIn(opcional['id'], [o['id'] for o in opcionales_de_variante(juego, grupo=self.tela)])
        self.assertIn(oculto['id'], [c.pk for c in self.fresco().cargos.all()])  # el producto los conserva
        # Un cargo en % no se permite en una agrupación (no tiene costo base propio).
        r = self.c.post('/api/listaprecios/cargos/', {'variante': juego.pk, 'descripcion': 'X', 'valor': 5, 'modo_valor': 'porcentaje'}, format='json')
        self.assertEqual(r.status_code, 400)


class GruposDelMaterialNuevoTests(LottusTestCase):
    """(2026-10-27) Con precios por grupo guardados, poner cuero (o tela) suma sus grupos solos:
    antes el grupo Cuero no salía en «Precios por grupo» hasta agregarlo a mano."""
    cargo = CargosPorcentajeYCueroTests.cargo
    patch_cargo = CargosPorcentajeYCueroTests.patch_cargo
    fresco = CargosPorcentajeYCueroTests.fresco

    def setUp(self):
        CargosPorcentajeYCueroTests.setUp(self)
        self.sofa.decimetraje_cuero = None
        self.sofa.save()
        PrecioVariante.objects.create(variante=self.sofa, grupo=self.tela)

    def grupos_venta(self):
        return [f['grupo'] for f in precios_por_variante(self.fresco())]

    def test_poner_cuero_al_producto_agrega_el_grupo_cuero_calculado(self):
        self.assertEqual(self.grupos_venta(), [self.tela.pk])
        r = self.c.patch(f'/api/listaprecios/variantes/{self.sofa.pk}/', {'decimetraje_cuero': '100'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.grupos_venta(), [self.tela.pk, self.cuero.pk])
        fila = next(p for p in r.data['precios'] if p['grupo'] == self.cuero.pk)
        self.assertIsNone(fila['precio_manual'])  # usa el calculado, con el dato al día
        # (1.000.000 + 100 dm × 1.000) × 2
        self.assertEqual(calcular_precio(self.fresco(), self.cuero), Decimal('2200000'))
        # Volver a guardar el consumo no duplica ni revive un grupo quitado a mano.
        PrecioVariante.objects.filter(variante=self.sofa, grupo=self.cuero).delete()
        self.c.patch(f'/api/listaprecios/variantes/{self.sofa.pk}/', {'decimetraje_cuero': '120'}, format='json')
        self.assertEqual(self.grupos_venta(), [self.tela.pk])

    def test_un_cargo_con_cuero_agrega_el_grupo_si_el_producto_no_tiene_consumo_propio(self):
        cargo = self.cargo(descripcion='Brazos')
        # Con tela propia, el cuero de un cargo no vuelve aplicable el grupo Cuero: no se agrega.
        self.assertEqual(self.patch_cargo(cargo, decimetraje_cuero='30').status_code, 200)
        self.assertFalse(PrecioVariante.objects.filter(variante=self.sofa, grupo=self.cuero).exists())
        VarianteProducto.objects.filter(pk=self.sofa.pk).update(metraje_tela=None)
        self.assertEqual(self.patch_cargo(cargo, decimetraje_cuero=None).status_code, 200)
        self.assertEqual(self.patch_cargo(cargo, decimetraje_cuero='30').status_code, 200)
        self.assertIn(self.cuero.pk, self.grupos_venta())

    def test_sin_precios_guardados_no_crea_filas(self):
        PrecioVariante.objects.filter(variante=self.sofa).delete()
        self.c.patch(f'/api/listaprecios/variantes/{self.sofa.pk}/', {'decimetraje_cuero': '100'}, format='json')
        self.assertFalse(PrecioVariante.objects.filter(variante=self.sofa).exists())
        self.assertIn(self.cuero.pk, self.grupos_venta())
