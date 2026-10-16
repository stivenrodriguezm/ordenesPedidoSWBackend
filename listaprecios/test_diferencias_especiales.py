"""Los especiales comerciales modifican el precio final en pesos exactos, sin cambiar costos."""
from decimal import Decimal

from rest_framework.exceptions import ValidationError
from ordenes.tests.utils import LottusTestCase
from .models import CategoriaLista, CargoVariante, EspecialLinea, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from .services import calcular_precio, costo_lista, opcionales_de_variante


class DiferenciasEspecialesTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General diferencias', valor=Decimal('1.76'), es_general=True)
        propio = Multiplicador.objects.create(nombre='Propio diferencias', valor=Decimal('2.30'))
        cat = CategoriaLista.objects.create(nombre='Salas delta', slug='salas-delta')
        self.linea = LineaProducto.objects.create(nombre='Referencia delta', slug='referencia-delta')
        self.a = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='235 cm', costo_base=Decimal('1000000'))
        self.b = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='200 cm', costo_base=Decimal('500000'), multiplicador=propio)
        self.c = self.api(self.crear_usuario('admin_delta', 'administrador'))
        self.url = '/api/listaprecios/especiales/'

    def crear(self, diferencia='100001', **extra):
        r = self.c.post(self.url, {'linea': self.linea.pk, 'nombre': 'Reclinable', 'diferencia_precio': diferencia, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_misma_diferencia_exacta_con_multiplicadores_distintos_y_costos_intactos(self):
        r = self.crear()
        self.assertEqual(Decimal(r['diferencia_precio']), Decimal('100001'))
        for v in [self.a, self.b]:
            cargo = v.cargos.get()
            self.assertEqual(cargo.tipo, CargoVariante.TIPO_DIFERENCIA_PRECIO)
            base = calcular_precio(v)
            self.assertEqual(calcular_precio(v, opcionales_ids=[cargo.pk]) - base, Decimal('100001'))
            self.assertEqual(opcionales_de_variante(v)[0]['valor'], Decimal('100001'))
            self.assertEqual(costo_lista(v, opcionales_ids=[cargo.pk]), costo_lista(v))

    def test_descuento_y_excepcion_individual_con_precio_manual(self):
        PrecioVariante.objects.create(variante=self.b, precio_manual='3000000')
        r = self.crear('-50000', aplicaciones=[{'variante': self.a.pk}, {'variante': self.b.pk, 'diferencia_precio': '-25000'}])
        self.assertEqual(calcular_precio(self.b, opcionales_ids=[self.b.cargos.get().pk]), Decimal('2975000'))
        self.assertEqual(calcular_precio(self.a, opcionales_ids=[self.a.cargos.get().pk]), Decimal('1710000'))
        renombrado = self.c.patch(f"{self.url}{r['id']}/", {'nombre': 'Otro acabado'}, format='json')
        self.assertEqual(renombrado.status_code, 200, renombrado.data)
        self.assertEqual(calcular_precio(self.b, opcionales_ids=[self.b.cargos.get().pk]), Decimal('2975000'))
        cambio = self.c.patch(f"{self.url}{r['id']}/", {'diferencia_precio': '100000', 'aplicaciones': [{'variante': self.a.pk, 'diferencia_precio': '100000'}, {'variante': self.b.pk, 'diferencia_precio': '-25000'}]}, format='json')
        self.assertEqual(cambio.status_code, 200, cambio.data)
        self.assertEqual(calcular_precio(self.a, opcionales_ids=[self.a.cargos.get().pk]), Decimal('1860000'))

    def test_juego_y_combinacion_con_cargo_de_costo_historico(self):
        self.a.componentes.create(variante=self.b, cantidad=2)
        self.crear('100001')
        legacy = self.a.cargos.create(descripcion='Costo anterior', valor='10000', opcional=True)
        nuevo = self.a.cargos.get(tipo=CargoVariante.TIPO_DIFERENCIA_PRECIO)
        base = calcular_precio(self.a)
        self.assertEqual(calcular_precio(self.a, opcionales_ids=[nuevo.pk, legacy.pk]), base + Decimal('100001') + Decimal('17600'))
        self.assertEqual(costo_lista(self.a, opcionales_ids=[nuevo.pk, legacy.pk]), costo_lista(self.a) + Decimal('10000'))

    def test_no_permite_que_la_combinacion_de_descuentos_deje_precio_negativo(self):
        self.crear('-1000000')
        cargo = self.a.cargos.get()
        otro = self.a.cargos.create(descripcion='Otro descuento', valor='-760001', tipo=CargoVariante.TIPO_DIFERENCIA_PRECIO, opcional=True)
        with self.assertRaises(ValidationError):
            calcular_precio(self.a, opcionales_ids=[cargo.pk, otro.pk])
        otro.valor = Decimal('-760000'); otro.save()
        self.assertEqual(calcular_precio(self.a, opcionales_ids=[cargo.pk, otro.pk]), 0)

    def test_datos_invalidos_no_dejan_especial_ni_cargos_parciales(self):
        for importe in ['NaN', 'Infinity', '', None, '100.50', '10000000000', '-9999999999']:
            r = self.c.post(self.url, {'linea': self.linea.pk, 'nombre': 'Inválido', 'diferencia_precio': importe}, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        for aplicaciones in [[], 'mal', [{'variante': self.a.pk, 'diferencia_precio': 'NaN'}], [{'variante': self.a.pk, 'diferencia_precio': '1.25'}], [{'variante': self.a.pk}, {'variante': self.a.pk}], [{'variante': 99999999}]]:
            r = self.c.post(self.url, {'linea': self.linea.pk, 'nombre': 'Inválido', 'diferencia_precio': '100', 'aplicaciones': aplicaciones}, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(EspecialLinea.objects.filter(linea=self.linea).exists())
        self.assertFalse(CargoVariante.objects.filter(variante__linea=self.linea).exists())

    def test_convertir_un_especial_historico_conserva_el_precio_para_cada_producto(self):
        legacy = self.c.post(self.url, {'linea': self.linea.pk, 'nombre': 'Anterior', 'valor': '100000'}, format='json')
        self.assertEqual(legacy.status_code, 201, legacy.data)
        self.assertEqual([Decimal(a['diferencia_precio']) for a in legacy.data['aplicaciones']], [Decimal('176000'), Decimal('230000')])
        antes = {v.pk: calcular_precio(v, opcionales_ids=[v.cargos.get().pk]) for v in [self.a, self.b]}
        convertido = self.c.patch(f"{self.url}{legacy.data['id']}/", {'diferencia_precio': legacy.data['diferencia_precio'], 'aplicaciones': [{'variante': a['variante'], 'diferencia_precio': a['diferencia_precio']} for a in legacy.data['aplicaciones']]}, format='json')
        self.assertEqual(convertido.status_code, 200, convertido.data)
        for v in [self.a, self.b]:
            self.assertEqual(calcular_precio(v, opcionales_ids=[v.cargos.get().pk]), antes[v.pk])

    def test_renombrar_preserva_las_fracciones_del_costo_historico(self):
        especial = EspecialLinea.objects.create(linea=self.linea, nombre='Histórico', valor=Decimal('12345.67'))
        cargo = self.a.cargos.create(especial=especial, descripcion=especial.nombre, valor=especial.valor, opcional=True)
        antes = calcular_precio(self.a, opcionales_ids=[cargo.pk])
        r = self.c.patch(f'{self.url}{especial.pk}/', {'nombre': 'Histórico renombrado'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        cargo.refresh_from_db()
        self.assertEqual(cargo.valor, Decimal('12345.67'))
        self.assertEqual(cargo.tipo, '')
        self.assertEqual(calcular_precio(self.a, opcionales_ids=[cargo.pk]), antes)
