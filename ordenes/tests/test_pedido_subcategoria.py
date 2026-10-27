"""Pedidos basados en referencia y subcategoría (2026-10-27)."""
from datetime import date

from ordenes.models import DetallePedido
from ordenes.tests.utils import LottusTestCase
from suministros.models import Categoria, Subcategoria


class PedidoConSubcategoriaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.api(self.crear_usuario('admin_pedido_sub', 'administrador'))
        self.prov = self.proveedor('Fábrica sub')
        self.ref = self.referencia(self.prov, 'Valencia sub')
        cat = Categoria.objects.create(nombre='Comedor sub')
        self.silla = Subcategoria.objects.create(categoria=cat, nombre='Silla sub')
        self.mesa = Subcategoria.objects.create(categoria=cat, nombre='Mesa sub')
        self.ajena = Subcategoria.objects.create(categoria=cat, nombre='Ajena sub')
        self.ref.subcategorias.add(self.silla, self.mesa)

    def crear(self, **detalle):
        return self.admin.post('/api/ordenes-pedido/', {'proveedor': self.prov.pk, 'fecha_esperada': str(date.today()),
                                                        'detalles': [{'referencia': self.ref.pk, 'cantidad': 6, 'especificaciones': 'Lino', **detalle}]}, format='json')

    def test_la_subcategoria_es_obligatoria_y_debe_ser_de_la_referencia(self):
        self.assertEqual(self.crear().status_code, 400)
        self.assertEqual(self.crear(subcategoria=self.ajena.pk).status_code, 400)
        r = self.crear(subcategoria=self.silla.pk)
        self.assertEqual(r.status_code, 201, r.data)
        detalle = DetallePedido.objects.get(orden_id=r.data['id'])
        self.assertEqual(detalle.subcategoria_id, self.silla.pk)
        d = self.admin.get(f"/api/pedidos/{r.data['id']}/detalles/").data
        self.assertEqual(d['detalles'][0]['subcategoria_nombre'], 'Silla sub')

    def test_una_referencia_sin_subcategorias_sigue_igual(self):
        otra = self.referencia(self.prov, 'Sin subcategorías')
        r = self.admin.post('/api/ordenes-pedido/', {'proveedor': self.prov.pk, 'fecha_esperada': str(date.today()),
                                                     'detalles': [{'referencia': otra.pk, 'cantidad': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(DetallePedido.objects.get(orden_id=r.data['id']).subcategoria_id)
