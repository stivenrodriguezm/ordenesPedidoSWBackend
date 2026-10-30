"""Volver a descargar la imagen del pedido de tela (2026-10-30): el listado trae el nombre
completo de quien lo pidió, como sale en la imagen al crearlo."""
from ordenes.models import PedidoTela, ProveedorTela
from ordenes.tests.utils import LottusTestCase


class NombreCompletoSolicitanteTests(LottusTestCase):
    def test_listado_trae_nombre_y_apellido(self):
        admin = self.crear_usuario('admin', role='administrador', first_name='Laura', last_name='Gómez')
        prov = ProveedorTela.objects.create(nombre_empresa='Textiles ficticios')
        PedidoTela.objects.create(id=1, usuario=admin, proveedor=prov, direccion_entrega='Bodega')
        data = self.api(admin).get('/api/pedidos-telas/').data
        fila = (data['results'] if isinstance(data, dict) else data)[0]
        self.assertEqual((fila['usuario_nombre'], fila['usuario_nombre_completo']), ('Laura', 'Laura Gómez'))
