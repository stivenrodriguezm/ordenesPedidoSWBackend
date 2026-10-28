"""(2026-10-28) Adicionales de una factura de proveedor: concepto, suma o resta y valor; el total
de la factura = productos + lo que suma − lo que resta."""
from suministros.models import AjusteFactura, FacturaProveedor
from ordenes.tests.utils import LottusTestCase


class AjustesFacturaTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin_ajustes', role='administrador')
        self.c = self.api(self.admin)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)

    def crear(self, valor, ajustes, id_manual='FA-1'):
        return self.c.post('/api/suministros/facturas/', {
            'id_manual': id_manual, 'proveedor': self.prov.pk, 'valor': valor, 'ajustes': ajustes,
            'productos': [{'referencia': self.ref.pk, 'costo': '100000', 'cantidad': 2}]}, format='json')

    def test_suma_y_resta_al_total_y_se_guardan(self):
        ajustes = [{'concepto': 'Transporte del proveedor', 'tipo': 'suma', 'valor': '50000'},
                   {'concepto': 'Descuento por pronto pago', 'tipo': 'resta', 'valor': '20000'}]
        self.assertEqual(self.crear('200000', ajustes).status_code, 400)  # sin contar los adicionales no cuadra
        r = self.crear('230000', ajustes)
        self.assertEqual(r.status_code, 201, r.data)
        factura = FacturaProveedor.objects.get(pk=r.data['id'])
        self.assertEqual([(a.concepto, a.tipo, a.importe) for a in factura.ajustes.all()],
                         [('Transporte del proveedor', 'suma', 50000), ('Descuento por pronto pago', 'resta', -20000)])
        datos = self.c.get(f'/api/suministros/facturas/{factura.pk}/').data
        self.assertEqual([a['concepto'] for a in datos['ajustes']], ['Transporte del proveedor', 'Descuento por pronto pago'])

    def test_validaciones(self):
        for malo in ({'concepto': ' ', 'tipo': 'suma', 'valor': '1000'}, {'concepto': 'X', 'tipo': 'otro', 'valor': '1000'},
                     {'concepto': 'X', 'tipo': 'suma', 'valor': '1000.50'}, {'concepto': 'X', 'tipo': 'resta', 'valor': '0'}):
            self.assertEqual(self.crear('201000', [malo]).status_code, 400, malo)
        self.assertFalse(AjusteFactura.objects.exists())

    def test_al_editar_la_lista_reemplaza_la_anterior(self):
        r = self.crear('210000', [{'concepto': 'Embalaje', 'tipo': 'suma', 'valor': '10000'}])
        fid = r.data['id']
        unidades = [i['id_referencia'] for i in r.data['items_inventario']]
        r = self.c.patch(f'/api/suministros/facturas/{fid}/', {
            'valor': '190000', 'ajustes': [{'concepto': 'Rayón en una pata', 'tipo': 'resta', 'valor': '10000'}],
            'productos': [{'id_referencias': unidades, 'referencia': self.ref.pk, 'costo': '100000', 'cantidad': 2}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(AjusteFactura.objects.filter(factura_id=fid).values_list('concepto', 'tipo')), [('Rayón en una pata', 'resta')])
