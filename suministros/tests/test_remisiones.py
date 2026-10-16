"""Regresiones de remisiones (H14, H15 · P04-03, P04-04 · anexo A).

La carrera real (dos transacciones MySQL simultáneas) vive en
lottus_tests/concurrencia y solo corre con settings_test_mysql."""
from datetime import date

from ordenes.tests.utils import LottusTestCase
from suministros.models import Inventario, RemisionSuministro
from suministros.serializers import RemisionSuministroSerializer


class RemisionesTests(LottusTestCase):
    def setUp(self):
        self.seller = self.crear_usuario('seller')
        self.owner = self.crear_usuario('owner')
        self.p1 = self.proveedor()
        self.ref = self.referencia(self.p1)

    def test_remision_put_bypasses_patch_permission(self):
        """Se conserva: PUT no permitido (405) aunque PATCH se niegue por permiso."""
        self.permisos('vendedor', ['VER_REMISIONES'])
        rem = RemisionSuministro.objects.create(vendedor=self.seller, fecha_entrega=date.today())
        c = self.api(self.seller)
        self.assertEqual(c.patch(f'/api/suministros/remisiones/{rem.pk}/', {'estado': 'anulada'}, format='json').status_code, 403)
        self.assertEqual(c.put(f'/api/suministros/remisiones/{rem.pk}/', {'estado': 'anulada'}, format='json').status_code, 405)
        rem.refresh_from_db()
        self.assertEqual(rem.estado, 'creada')

    def test_remision_read_permission_can_delete(self):
        """Se conserva: DELETE no permitido e inventario intacto."""
        self.permisos('vendedor', ['VER_REMISIONES'])
        inv = Inventario.objects.create(id_referencia='R1', referencia=self.ref, disponibilidad='por_despachar')
        rem = RemisionSuministro.objects.create(vendedor=self.seller, fecha_entrega=date.today())
        rem.inventario_items.add(inv)
        r = self.api(self.seller).delete(f'/api/suministros/remisiones/{rem.pk}/')
        self.assertEqual(r.status_code, 405)
        inv.refresh_from_db()
        self.assertEqual(inv.disponibilidad, 'por_despachar')
        self.assertTrue(RemisionSuministro.objects.filter(pk=rem.pk).exists())

    def test_remision_reserves_inventory_of_foreign_sale(self):
        self.permisos('vendedor', ['CREAR_REMISION'])
        propia = self.venta(self.seller)
        ajena = self.venta(self.owner)
        item = Inventario.objects.create(id_referencia='AJENO', referencia=self.ref, venta=ajena, disponibilidad='cliente')
        r = self.api(self.seller).post('/api/suministros/remisiones/', {
            'ventas': [propia.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [item.pk],
        }, format='json')
        self.assertEqual(r.status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.disponibilidad, 'cliente')
        self.assertEqual(item.remisiones_suministros.count(), 0)

    def test_item_de_la_venta_propia_y_stock_libre_admitidos(self):
        self.permisos('vendedor', ['CREAR_REMISION'])
        propia = self.venta(self.seller)
        mio = Inventario.objects.create(id_referencia='MIO', referencia=self.ref, venta=propia, disponibilidad='cliente')
        libre = Inventario.objects.create(id_referencia='LIBRE', referencia=self.ref, disponibilidad='exhibicion')
        r = self.api(self.seller).post('/api/suministros/remisiones/', {
            'ventas': [propia.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [mio.pk, libre.pk],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        for i in (mio, libre):
            i.refresh_from_db()
            self.assertEqual(i.disponibilidad, 'por_despachar')

    def test_item_libre_no_disponible_rechazado(self):
        """Stock sin venta solo es asignable si está en exhibición/consignación."""
        self.permisos('vendedor', ['CREAR_REMISION'])
        propia = self.venta(self.seller)
        no_venta = Inventario.objects.create(id_referencia='NOVENTA', referencia=self.ref, disponibilidad='no_venta')
        r = self.api(self.seller).post('/api/suministros/remisiones/', {
            'ventas': [propia.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [no_venta.pk],
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_interleaved_remision_validation_allows_double_reservation(self):
        """Dos validaciones antes de guardar: la segunda escritura se rechaza
        dentro de su transacción (comprobación con bloqueo al guardar)."""
        item = Inventario.objects.create(id_referencia='RACE', referencia=self.ref, disponibilidad='exhibicion')
        payload = {'fecha_entrega': str(date.today()), 'inventario_items': [item.pk]}
        s1 = RemisionSuministroSerializer(data=payload)
        s2 = RemisionSuministroSerializer(data=payload)
        self.assertTrue(s1.is_valid())
        self.assertTrue(s2.is_valid())
        s1.save()
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            s2.save()
        self.assertEqual(item.remisiones_suministros.count(), 1)
