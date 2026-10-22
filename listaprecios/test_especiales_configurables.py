"""Persistencia, biblioteca, costo/margen propios y materiales independientes de los especiales."""
from decimal import Decimal

from rest_framework.exceptions import ValidationError
from ordenes.tests.utils import LottusTestCase
from .models import CargoVariante, CategoriaLista, EspecialCatalogo, EspecialLinea, GrupoTela, LineaProducto, Multiplicador, PrecioVariante, VarianteProducto
from .services import calcular_precio, costo_lista


class EspecialesConfigurablesTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        Multiplicador.objects.create(nombre='General especiales', valor=Decimal('1.76'), es_general=True)
        cat = CategoriaLista.objects.create(nombre='Salas especiales', slug='salas-especiales')
        self.linea = LineaProducto.objects.create(nombre='Colección A', slug='coleccion-a')
        self.a = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='235 cm', costo_base=Decimal('1000000'), metraje_tela=Decimal('10'), decimetraje_cuero=Decimal('120'))
        self.b = VarianteProducto.objects.create(linea=self.linea, categoria=cat, nombre='200 cm', costo_base=Decimal('800000'), metraje_tela=Decimal('8'), decimetraje_cuero=Decimal('100'))
        self.tela = GrupoTela.objects.create(nombre='Tela especial', tipo='tela', precio_por_metro=Decimal('50000'))
        self.cuero = GrupoTela.objects.create(nombre='Cuero especial', tipo='cuero', precio_por_metro=Decimal('10000'))
        self.admin = self.api(self.crear_usuario('admin_especiales_config', 'administrador'))
        self.url = '/api/listaprecios/especiales/'
        self.config = dict(costo_base='100000', multiplicador='2.5', sentido='sube', metraje_tela=None, decimetraje_cuero=None)

    def crear(self, config=None, **extra):
        r = self.admin.post(self.url, {'linea': self.linea.pk, 'nombre': 'Reclinable', 'configuracion': config or self.config, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_guarda_costo_y_multiplo_y_persisten_al_recargar(self):
        r = self.crear()
        get = self.admin.get(f"{self.url}{r['id']}/")
        self.assertEqual(get.status_code, 200, get.data)
        self.assertEqual(get.data['configuracion'], self.config)
        for v in [self.a, self.b]:
            cargo = v.cargos.get()
            self.assertEqual(cargo.tipo, CargoVariante.TIPO_ESPECIAL_CONFIGURABLE)
            self.assertEqual(calcular_precio(v, self.tela, [cargo.pk]) - calcular_precio(v, self.tela), Decimal('250000'))
            self.assertEqual(costo_lista(v, self.tela, [cargo.pk]) - costo_lista(v, self.tela), Decimal('100000'))

    def test_cada_material_usa_el_consumo_independiente_y_el_multiplo_del_especial(self):
        self.vincular_subcategorias_catalogo(self.linea)
        self.crear({**self.config, 'metraje_tela': '2.5', 'decimetraje_cuero': '35'})
        cargo = self.a.cargos.get()
        for grupo, diferencia, costo in [(self.tela, '562500', '225000'), (self.cuero, '1125000', '450000')]:
            self.assertEqual(calcular_precio(self.a, grupo, [cargo.pk]) - calcular_precio(self.a, grupo), Decimal(diferencia))
            self.assertEqual(costo_lista(self.a, grupo, [cargo.pk]) - costo_lista(self.a, grupo), Decimal(costo))
            r = self.admin.get(f'/api/listaprecios/variantes/{self.a.pk}/precio/', {'grupo': grupo.pk, 'opcionales': str(cargo.pk)})
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(Decimal(str(r.data['opcionales_incluidos'][0]['valor'])), Decimal(diferencia))

    def test_precio_manual_y_multiplicador_del_producto_no_multiplican_dos_veces_el_especial(self):
        mult = Multiplicador.objects.create(nombre='Producto especial', valor=Decimal('3.7'))
        self.a.multiplicador = mult; self.a.save()
        PrecioVariante.objects.create(variante=self.a, grupo=self.tela, precio_manual=Decimal('3000000'))
        self.crear()
        self.assertEqual(calcular_precio(self.a, self.tela, [self.a.cargos.get().pk]), Decimal('3250000'))

    def test_aplica_general_mantiene_excepciones_y_permite_restablecerlas(self):
        r = self.crear(aplicaciones=[{'variante': self.a.pk}, {'variante': self.b.pk, 'configuracion': {'costo_base': '200000', 'multiplicador': '3'}}])
        actualizado = self.admin.patch(f"{self.url}{r['id']}/", {'configuracion': {**self.config, 'costo_base': '150000'}}, format='json')
        self.assertEqual(actualizado.status_code, 200, actualizado.data)
        self.assertEqual(calcular_precio(self.a, self.tela, [self.a.cargos.get().pk]) - calcular_precio(self.a, self.tela), Decimal('375000'))
        self.assertEqual(calcular_precio(self.b, self.tela, [self.b.cargos.get().pk]) - calcular_precio(self.b, self.tela), Decimal('600000'))
        reset = self.admin.patch(f"{self.url}{r['id']}/", {'aplicaciones': [{'variante': self.a.pk}, {'variante': self.b.pk}]}, format='json')
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertEqual(self.b.cargos.get().configuracion_especial, {})

    def test_biblioteca_se_reutiliza_en_otra_coleccion_y_sobrevive_al_borrado(self):
        r = self.crear()
        biblioteca = self.admin.get(self.url + 'biblioteca/')
        self.assertEqual(biblioteca.status_code, 200, biblioteca.data)
        plantilla = next(e for e in biblioteca.data if e['nombre'] == 'Reclinable')
        otra = LineaProducto.objects.create(nombre='Colección B', slug='coleccion-b')
        VarianteProducto.objects.create(linea=otra, categoria=self.a.categoria, nombre='Otro sofá', costo_base=Decimal('2000000'))
        copia = self.admin.post(self.url, {'linea': otra.pk, 'nombre': plantilla['nombre'], 'configuracion': plantilla['configuracion']}, format='json')
        self.assertEqual(copia.status_code, 201, copia.data)
        self.assertEqual(EspecialCatalogo.objects.filter(nombre='Reclinable').count(), 1)
        editar = self.admin.patch(f"{self.url}{copia.data['id']}/", {'configuracion': {**self.config, 'costo_base': '250000'}}, format='json')
        self.assertEqual(editar.status_code, 200, editar.data)
        self.assertEqual(EspecialLinea.objects.get(pk=r['id']).configuracion['costo_base'], '100000')
        self.admin.delete(f"{self.url}{r['id']}/")
        self.admin.delete(f"{self.url}{copia.data['id']}/")
        self.assertEqual(EspecialCatalogo.objects.filter(nombre='Reclinable').count(), 2)

    def test_no_acepta_centavos_consumos_invalidos_ni_productos_ajenos_y_es_atomico(self):
        for campo, valor in [('costo_base', '10.5'), ('costo_base', ''), ('costo_base', '-100'), ('multiplicador', '0'), ('multiplicador', 'NaN'), ('multiplicador', '2.1234'), ('metraje_tela', '0'), ('decimetraje_cuero', '-1')]:
            r = self.admin.post(self.url, {'linea': self.linea.pk, 'nombre': 'Inválido', 'configuracion': {**self.config, campo: valor}}, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        for aplicaciones in [[], [{'variante': self.a.pk}, {'variante': 999999}], [{'variante': self.a.pk}, {'variante': self.a.pk}], [{'variante': self.a.pk, 'configuracion': {'costo_base': '1.25'}}]]:
            r = self.admin.post(self.url, {'linea': self.linea.pk, 'nombre': 'Inválido', 'configuracion': self.config, 'aplicaciones': aplicaciones}, format='json')
            self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(EspecialLinea.objects.filter(linea=self.linea).exists())
        self.assertFalse(CargoVariante.objects.filter(variante__linea=self.linea).exists())
        self.assertFalse(EspecialCatalogo.objects.filter(nombre='Inválido').exists())

    def test_material_no_habilitado_no_se_puede_cotizar_ni_expone_costos_al_vendedor(self):
        self.vincular_subcategorias_catalogo(self.linea)
        self.crear({**self.config, 'metraje_tela': '2'})
        cargo = self.a.cargos.get()
        with self.assertRaises(ValidationError):
            calcular_precio(self.a, self.cuero, [cargo.pk])
        r = self.admin.get('/api/listaprecios/catalogo/')
        linea = next(l for l in r.data if l['id'] == self.linea.pk)
        op = linea['variantes'][0]['opcionales'][0]
        self.assertNotIn('configuracion', op)
        self.assertNotIn('costo_base', op)
        self.assertEqual(op['precios'], [{'grupo': self.tela.pk, 'valor': Decimal('500000')}])

    def test_baja_el_precio_con_costo_y_multiplo_y_rechaza_totales_negativos(self):
        self.crear({**self.config, 'sentido': 'baja'})
        self.assertEqual(calcular_precio(self.a, self.tela, [self.a.cargos.get().pk]) - calcular_precio(self.a, self.tela), Decimal('-250000'))
        r = self.admin.post(self.url, {'linea': self.linea.pk, 'nombre': 'Demasiado', 'configuracion': {**self.config, 'sentido': 'baja', 'costo_base': '9000000'}}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_biblioteca_no_es_publica_para_el_vendedor_sin_permiso_de_costos(self):
        vendedor = self.api(self.crear_usuario('vendedor_biblioteca', 'vendedor'))
        self.assertEqual(vendedor.get(self.url + 'biblioteca/').status_code, 403)

    def test_contrato_anterior_y_renombrado_alimentan_la_biblioteca_sin_convertir_el_calculo(self):
        r = self.admin.post(self.url, {'linea': self.linea.pk, 'nombre': 'Antiguo', 'valor': '150000'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        cargo = self.a.cargos.get()
        antes = calcular_precio(self.a, self.tela, [cargo.pk])
        editado = self.admin.patch(f"{self.url}{r.data['id']}/", {'nombre': 'Antiguo renombrado'}, format='json')
        self.assertEqual(editado.status_code, 200, editado.data)
        self.assertTrue(EspecialCatalogo.objects.filter(nombre='Antiguo renombrado').exists())
        self.assertEqual(EspecialLinea.objects.get(pk=r.data['id']).configuracion, {})
        self.assertEqual(calcular_precio(self.a, self.tela, [cargo.pk]), antes)
