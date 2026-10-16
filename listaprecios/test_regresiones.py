"""Regresiones de lista de precios (H08, H19 · P02-02, P05-03 · anexo A)."""
from decimal import Decimal

from listaprecios.models import CategoriaLista, LineaProducto, Multiplicador, VarianteProducto
from ordenes.tests.utils import LottusTestCase


class PreciosPermisosTests(LottusTestCase):
    def setUp(self):
        Multiplicador.objects.all().delete()
        self.general = Multiplicador.objects.create(nombre='General', valor=Decimal('1.76'), es_general=True)
        self.mult = Multiplicador.objects.create(nombre='Especial', valor=Decimal('2'))
        cat = CategoriaLista.objects.create(nombre='Prueba', slug='prueba')
        linea = LineaProducto.objects.create(nombre='Prueba', slug='prueba')
        self.variante = VarianteProducto.objects.create(linea=linea, categoria=cat, nombre='V', costo_base=Decimal('100'))
        self.admin = self.crear_usuario('admin', role='administrador')

    def test_read_price_permission_allows_bulk_mutation(self):
        lector = self.crear_usuario('lector', role='marketing')
        self.permisos('marketing', ['VER_COSTOS_LISTA_PRECIOS'])
        r = self.api(lector).post('/api/listaprecios/variantes/asignar-multiplicador/', {
            'multiplicador': self.mult.pk, 'variante_ids': [self.variante.pk],
        }, format='json')
        self.assertEqual(r.status_code, 403)
        self.variante.refresh_from_db()
        self.assertIsNone(self.variante.multiplicador_id)

    def test_editor_si_asigna(self):
        r = self.api(self.admin).post('/api/listaprecios/variantes/asignar-multiplicador/', {
            'multiplicador': self.mult.pk, 'variante_ids': [self.variante.pk],
        }, format='json')
        self.assertEqual(r.status_code, 200)

    def test_catalog_general_multiplier_can_be_unset(self):
        r = self.api(self.admin).patch(f'/api/listaprecios/multiplicadores/{self.general.pk}/', {'es_general': False}, format='json')
        self.assertEqual(r.status_code, 400)
        self.general.refresh_from_db()
        self.assertTrue(self.general.es_general)
        self.assertEqual(Multiplicador.objects.filter(es_general=True).count(), 1)

    def test_reemplazo_atomico_del_general(self):
        r = self.api(self.admin).patch(f'/api/listaprecios/multiplicadores/{self.mult.pk}/', {'es_general': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(Multiplicador.objects.filter(es_general=True).values_list('pk', flat=True)), [self.mult.pk])

    def test_sin_general_no_cae_silenciosamente_a_uno(self):
        from listaprecios.services import obtener_multiplicador_general, ConfiguracionPreciosIncompleta
        Multiplicador.objects.filter(es_general=True).update(es_general=False)
        with self.assertRaises(ConfiguracionPreciosIncompleta):
            obtener_multiplicador_general()
        vendedor = self.crear_usuario('vend')
        self.permisos('vendedor', ['VER_LISTA_PRECIOS'])
        r = self.api(vendedor).get(f'/api/listaprecios/variantes/{self.variante.pk}/precio/')
        self.assertEqual(r.status_code, 409)

    def test_multiplicador_no_positivo_rechazado(self):
        r = self.api(self.admin).post('/api/listaprecios/multiplicadores/', {'nombre': 'Cero', 'valor': '0'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api(self.admin).post('/api/listaprecios/multiplicadores/', {'nombre': 'Neg', 'valor': '-1'}, format='json')
        self.assertEqual(r.status_code, 400)
