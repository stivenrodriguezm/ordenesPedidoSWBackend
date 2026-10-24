from io import BytesIO

from openpyxl import load_workbook

from ordenes.models import Cliente
from ordenes.serializers import ClienteSerializer
from ordenes.tests.utils import LottusTestCase


class TipoPersonaClienteTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin-tipo-cliente', role='administrador')
        self.api_admin = self.api(self.admin)
        self.natural = self.cliente('0012345', 'Cliente natural de prueba')
        self.juridica = Cliente.objects.create(nombre='Empresa de prueba SAS', cedula='900123456-7',
                                               tipo_persona='juridica', telefono1='000')

    def test_compatibilidad_y_edicion_sin_cambiar_identidad_ni_ventas(self):
        self.assertEqual(self.natural.tipo_persona, 'natural')
        venta = self.venta(self.admin, cliente=self.natural)
        r = self.api_admin.put(f'/api/clientes/{self.natural.pk}/',
            {'tipo_persona': 'juridica', 'nombre': 'Empresa reclasificada', 'cedula': '900001234-5'}, format='json')
        self.assertEqual(r.status_code, 200)
        venta.refresh_from_db()
        self.assertEqual(venta.cliente_id, self.natural.pk)
        self.assertEqual(r.data['tipo_persona'], 'juridica')
        # Un cliente antiguo de la API que solo cambia teléfono conserva el tipo.
        r = self.api_admin.put(f'/api/clientes/{self.natural.pk}/', {'telefono1': '12345'}, format='json')
        self.assertEqual(r.data['tipo_persona'], 'juridica')

    def test_filtros_de_directorio_y_excel_usan_mismo_tipo(self):
        r = self.api_admin.get('/api/clientes/?tipo_persona=juridica&search=prueba')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c['id'] for c in r.data['results']], [self.juridica.pk])
        r = self.api_admin.post('/api/clientes/exportar/?tipo_persona=juridica&search=prueba', {}, format='json')
        self.assertEqual(r.status_code, 200)
        rows = list(load_workbook(BytesIO(r.content)).active.values)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][-1], 'Tipo de persona')
        self.assertEqual(rows[1][-1], 'Persona jurídica')
        self.assertEqual(rows[1][2], '900123456-7')

    def test_validacion_tipo_y_documento_unico(self):
        datos = {'nombre': 'Otra empresa', 'cedula': '900123456-7', 'telefono1': '000', 'tipo_persona': 'juridica'}
        s = ClienteSerializer(data=datos)
        self.assertFalse(s.is_valid())
        self.assertIn('cedula', s.errors)
        r = self.api_admin.put(f'/api/clientes/{self.natural.pk}/', {'tipo_persona': 'otro'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('tipo_persona', r.data)
        self.assertEqual(self.api_admin.get('/api/clientes/?tipo_persona=otro').status_code, 400)

    def test_detalle_venta_lleva_tipo_para_editar_etiquetas(self):
        from ordenes.serializers import ClienteDetalleSerializer
        self.assertEqual(ClienteDetalleSerializer(self.juridica).data['tipo_persona'], 'juridica')

    def test_crear_y_editar_cliente_desde_venta(self):
        from ordenes.models import Venta
        r = self.api_admin.post('/api/ventas/crear/', {
            'cliente_nuevo': True,
            'cliente': {'nombre': 'Nueva empresa ficticia', 'cedula': '900222333-4',
                        'tipo_persona': 'juridica', 'telefono1': '000'},
            'venta': {'id': 998123, 'id_vendedor': self.admin.pk, 'valor_total': '1000000',
                      'fecha_venta': '2026-10-24', 'fecha_entrega': '2026-10-30', 'sede': 'Lottus 1'},
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        venta = Venta.objects.get(pk=r.data['venta_id'])
        self.assertEqual(venta.cliente.tipo_persona, 'juridica')
        r = self.api_admin.put(f'/api/ventas/{venta.pk}/editar/', {
            'cliente': {'id': venta.cliente_id, 'tipo_persona': 'natural', 'nombre': 'Persona ficticia'},
            'venta': {},
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        venta.cliente.refresh_from_db()
        self.assertEqual(venta.cliente.tipo_persona, 'natural')
        self.assertEqual(venta.cliente.nombre, 'Persona ficticia')
