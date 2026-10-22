"""Transporte por envío (2026-10-21): uno por conjunto (el mayor) y cupo de unidades por transporte."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache

from ordenes.tests.utils import LottusTestCase
from .models import CargoVariante, CategoriaLista, Cotizacion, GrupoTela, LineaProducto, Multiplicador, VarianteProducto
from .services import calcular_precio, costo_lista
from .transportes import calcular_compartidos


class TransportesTests(LottusTestCase):
    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_transportes', 'administrador'))
        cat = CategoriaLista.objects.create(nombre='Comedores transporte', slug='comedores-transporte')
        self.linea = LineaProducto.objects.create(nombre='Comedor transporte', slug='comedor-transporte')
        self.mesa = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='Mesa', costo_base=500000)
        self.silla = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='Silla', costo_base=100000, metraje_tela=1)
        self.juego = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='Comedor 6', costo_base=0)
        self.grupo = GrupoTela.objects.create(nombre='Grupo transporte', precio_por_metro=10000)
        self.transporte(self.mesa, 30000)
        self.t_silla = self.transporte(self.silla, 20000, cupo=6)

    def transporte(self, variante, valor, cupo=None):
        r = self.c.post('/api/listaprecios/cargos/', {'variante': variante.pk, 'tipo': 'transporte', 'valor': valor, 'unidades_por_transporte': cupo}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def fresca(self, v):
        return VarianteProducto.objects.get(pk=v.pk)

    def test_boton_transporte_crea_uno_solo_con_su_valor_y_cupo_valido(self):
        otra = VarianteProducto.objects.create(linea=self.linea, categoria=self.mesa.categoria, nombre='Bife', costo_base=1)
        r = self.c.post('/api/listaprecios/cargos/', {'variante': otra.pk, 'tipo': 'transporte'}, format='json')
        self.assertEqual((r.status_code, r.data['descripcion'], Decimal(r.data['valor']), r.data['opcional']), (201, 'Transporte', Decimal(120000), False))
        self.assertEqual(self.c.post('/api/listaprecios/cargos/', {'variante': otra.pk, 'tipo': 'transporte'}, format='json').status_code, 400)
        url = f"/api/listaprecios/cargos/{r.data['id']}/"
        self.assertEqual(self.c.patch(url, {'unidades_por_transporte': 0}, format='json').status_code, 400)
        self.assertEqual(self.c.patch(url, {'unidades_por_transporte': 4}, format='json').data['unidades_por_transporte'], 4)
        # El cupo no aplica a otros cargos.
        otro = self.c.post('/api/listaprecios/cargos/', {'variante': otra.pk, 'descripcion': 'Armado', 'valor': 1, 'unidades_por_transporte': 3}, format='json')
        self.assertIsNone(otro.data['unidades_por_transporte'])

    def test_un_producto_suelto_lleva_su_transporte_en_el_precio(self):
        # (100.000 + 1 m × 10.000 + 20.000 de transporte) × 2
        self.assertEqual(calcular_precio(self.fresca(self.silla), self.grupo), Decimal('260000'))

    def test_el_conjunto_cobra_un_solo_transporte_el_mayor(self):
        r = self.c.put(f'/api/listaprecios/variantes/{self.juego.pk}/componentes/',
                       {'componentes': [{'variante': self.mesa.pk, 'cantidad': 1}, {'variante': self.silla.pk, 'cantidad': 6}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        juego = self.fresca(self.juego)
        # Mesa 1.060.000 + 6 sillas × 260.000 = 2.620.000, menos los 6 transportes de las sillas (se cobra el de la mesa).
        self.assertEqual(calcular_precio(juego, self.grupo), Decimal('2380000'))
        self.assertEqual(costo_lista(juego, self.grupo), Decimal('1190000'))
        from .serializers import VarianteCatalogoSerializer
        self.assertIsNone(VarianteCatalogoSerializer().get_transporte(juego))
        self.assertEqual(VarianteCatalogoSerializer(context={}).get_transporte(self.fresca(self.silla)),
                         {'id': self.t_silla['id'], 'valor': Decimal('40000'), 'cupo': 6, 'opcional': False})

    def test_cupo_de_unidades_y_productos_distintos(self):
        silla, mesa = self.fresca(self.silla), self.fresca(self.mesa)
        r = calcular_compartidos([{'clave': 's', 'variante': silla, 'cantidad': 6}, {'clave': 'm', 'variante': mesa, 'cantidad': 2}])
        # 6 sillas caben en un transporte (se descuentan los otros 5); las 2 mesas (sin cupo) van en uno.
        self.assertEqual(r, {'s': {'transportes': 1, 'valor': Decimal('200000')}, 'm': {'transportes': 1, 'valor': Decimal('60000')}})
        r = calcular_compartidos([{'clave': 's', 'variante': silla, 'cantidad': 7}])
        self.assertEqual(r, {'s': {'transportes': 2, 'valor': Decimal('200000')}})
        # Un opcional deshabilitado no se cuenta si no se elige.
        CargoVariante.objects.filter(pk=self.t_silla['id']).update(opcional=True)
        silla = self.fresca(self.silla)
        self.assertEqual(calcular_compartidos([{'clave': 's', 'variante': silla, 'cantidad': 7, 'opcionales': []}]), {})

    def test_cotizacion_con_piezas_reunidas_en_un_conjunto(self):
        lineas = [{'variante': self.mesa.pk, 'cantidad': 1, 'precio_unitario': 1060000, 'conjunto': 'c1', 'linea_nombre': 'Comedor', 'variante_nombre': 'Mesa'},
                  {'variante': self.silla.pk, 'grupo_tela': self.grupo.pk, 'cantidad': 6, 'precio_unitario': 260000, 'conjunto': 'c1', 'linea_nombre': 'Comedor', 'variante_nombre': 'Silla'},
                  {'variante': self.silla.pk, 'grupo_tela': self.grupo.pk, 'cantidad': 7, 'precio_unitario': 260000, 'linea_nombre': 'Comedor', 'variante_nombre': 'Silla'}]
        r = self.c.post('/api/listaprecios/cotizaciones/', {'cliente_nombre': 'Ana', 'descuento': 0, 'lineas': lineas}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cot = Cotizacion.objects.get(pk=r.data['id'])
        mesa, sillas_conjunto, sillas_sueltas = cot.lineas.order_by('id')
        self.assertEqual([l.transporte_compartido for l in (mesa, sillas_conjunto, sillas_sueltas)], [Decimal(0), Decimal('240000'), Decimal('200000')])
        self.assertEqual(cot.subtotal, Decimal(1060000 + 6 * 260000 + 7 * 260000 - 240000 - 200000))


class OrdenYNombresDeCargosTests(LottusTestCase):
    """2026-10-21: los cargos se ordenan como las subcategorías y sus nombres se sugieren al escribir."""

    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_orden_cargos', 'administrador'))
        cat = CategoriaLista.objects.create(nombre='Sala orden', slug='sala-orden')
        linea = LineaProducto.objects.create(nombre='Sala orden', slug='sala-orden')
        self.sofa = VarianteProducto.objects.create(linea=linea, categoria=cat, nombre='Sofá', costo_base=100)
        self.otro = VarianteProducto.objects.create(linea=linea, categoria=cat, nombre='Poltrona', costo_base=100)

    def cargo(self, variante, nombre, **extra):
        r = self.c.post('/api/listaprecios/cargos/', {'variante': variante.pk, 'descripcion': nombre, 'valor': 1000, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_los_cargos_nuevos_van_al_final_y_se_reordenan(self):
        a, b, t = self.cargo(self.sofa, 'USB'), self.cargo(self.sofa, 'Brazos'), self.c.post('/api/listaprecios/cargos/', {'variante': self.sofa.pk, 'tipo': 'transporte'}, format='json').data
        self.assertEqual([a['orden'], b['orden'], t['orden']], [0, 1, 2])
        url = f'/api/listaprecios/variantes/{self.sofa.pk}/orden-cargos/'
        r = self.c.post(url, {'cargos': [t['id'], a['id'], b['id']]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(self.sofa.cargos.values_list('pk', flat=True)), [t['id'], a['id'], b['id']])
        # Incompleto, repetido o de otro producto: se rechaza sin cambiar nada.
        ajeno = self.cargo(self.otro, 'Ajeno')
        for ids in ([a['id'], b['id']], [a['id'], a['id'], b['id']], [t['id'], a['id'], ajeno['id']]):
            self.assertEqual(self.c.post(url, {'cargos': ids}, format='json').status_code, 400)
        self.assertEqual(list(self.sofa.cargos.values_list('pk', flat=True)), [t['id'], a['id'], b['id']])

    def test_sugiere_los_nombres_ya_usados_los_mas_comunes_primero(self):
        self.cargo(self.sofa, 'USB'); self.cargo(self.otro, 'USB'); self.cargo(self.otro, 'Brazos'); self.cargo(self.otro, 'Nuevo cargo')
        r = self.c.get('/api/listaprecios/cargos/nombres/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[:2], ['USB', 'Brazos'])
        self.assertNotIn('Nuevo cargo', r.data)


class CantidadesYConsultaTests(LottusTestCase):
    """2026-10-21: un adicional puede ir varias veces; los grupos se ordenan; los obligatorios se ven."""

    def setUp(self):
        cache.clear()
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General', valor=2, es_general=True)
        self.c = self.api(self.crear_usuario('admin_cantidades', 'administrador'))
        cat = CategoriaLista.objects.create(nombre='Sala cantidades', slug='sala-cantidades')
        self.linea = LineaProducto.objects.create(nombre='Montecarlo prueba', slug='montecarlo-prueba', activo=True)
        self.sofa = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='Sofá 2p.', costo_base=1000, publicado=True, costo_confirmado=True)
        self.reclino = CargoVariante.objects.create(variante=self.sofa, descripcion='Reclino eléctrico', valor=500, opcional=True)
        self.transporte = CargoVariante.objects.create(variante=self.sofa, descripcion='Transporte', valor=100, tipo='transporte', opcional=True, preseleccionado=True)
        CargoVariante.objects.create(variante=self.sofa, descripcion='Armado', valor=50)

    def test_dos_reclinos_cuentan_doble_y_cojines_o_transporte_solo_uno(self):
        sofa = VarianteProducto.objects.get(pk=self.sofa.pk)
        base = calcular_precio(sofa, None, [])
        self.assertEqual(calcular_precio(sofa, None, [self.reclino.pk, self.reclino.pk]) - base, Decimal(2000))
        self.assertEqual(costo_lista(sofa, None, [{'id': self.reclino.pk, 'cantidad': 2}]) - costo_lista(sofa, None, []), Decimal(1000))
        url = f'/api/listaprecios/variantes/{self.sofa.pk}/precio/'
        # La consulta solo calcula productos publicados de una referencia; aquí basta la ficha de prueba.
        with mock.patch('listaprecios.views.productos_actuales', lambda: VarianteProducto.objects.all()):
            r = self.c.get(url, {'opcionales': f'{self.reclino.pk},{self.reclino.pk}'})
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(Decimal(r.data['precio']), base + 2000)
            self.assertEqual(r.data['opcionales_incluidos'][0]['cantidad'], 2)
            self.assertEqual(self.c.get(url, {'opcionales': f'{self.transporte.pk},{self.transporte.pk}'}).status_code, 400)
            self.assertEqual(self.c.get(url, {'opcionales': ','.join([str(self.reclino.pk)] * 10)}).status_code, 400)

    def test_la_consulta_muestra_obligatorios_y_marca_los_multiples(self):
        from .serializers import VarianteCatalogoSerializer
        datos = VarianteCatalogoSerializer(VarianteProducto.objects.get(pk=self.sofa.pk), context={}).data
        self.assertEqual(datos['incluidos'], ['Armado'])
        multiples = {o['descripcion']: o['multiple'] for o in datos['opcionales']}
        self.assertEqual(multiples, {'Reclino eléctrico': True, 'Transporte': False})

    def test_los_grupos_de_tela_se_reordenan_completos(self):
        g1 = GrupoTela.objects.create(nombre='G orden 1', orden=1)
        g2 = GrupoTela.objects.create(nombre='G orden 2', orden=2)
        todos = list(GrupoTela.objects.values_list('pk', flat=True))
        nuevo = [g2.pk] + [pk for pk in todos if pk != g2.pk]
        r = self.c.post('/api/listaprecios/grupos-tela/ordenar/', {'grupos': nuevo}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(GrupoTela.objects.values_list('pk', flat=True)), nuevo)
        self.assertEqual(self.c.post('/api/listaprecios/grupos-tela/ordenar/', {'grupos': [g1.pk]}, format='json').status_code, 400)
