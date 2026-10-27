"""Anular un pedido de tela desde «Editar estado» (2026-10-26): permiso ANULAR_PEDIDO_TELA,
inicialmente solo del administrador. El pedido no se borra; queda Anulado con su motivo y la
tela de sus productos vuelve a quedar por pedir."""
from importlib import import_module

from django.apps import apps
from django.db import connection

from ordenes.models import OrdenPedido, PedidoTela, RegistroAuditoria, RolePermission
from ordenes.tests import test_gestion_telas
from ordenes.tests.utils import LottusTestCase


class AnularPedidoTelaTests(LottusTestCase):
    _base = test_gestion_telas.GestionYTelasTests
    fila, guardar, pedir = _base.fila, _base.guardar, _base.pedir
    tela_aparte, pedir_telas = _base.tela_aparte, _base.pedir_telas

    def setUp(self):
        self._base.setUp(self)
        d = self.guardar([self.tela_aparte()])
        self.pedir(d)
        r = self.pedir_telas(self.api_asesor.get(self.url).data)
        self.assertEqual(r.status_code, 201, r.data)
        self.pedido = PedidoTela.objects.get()
        self.op = OrdenPedido.objects.get(pk=self.pedido.orden_asociada_id)

    def anular(self, cliente=None, motivo='Se pidió con el color equivocado'):
        return (cliente or self.api_admin).patch(f'/api/pedidos-telas/{self.pedido.pk}/', {'estado': 'Anulado', 'motivo_anulacion': motivo}, format='json')

    def test_el_administrador_anula_con_motivo_y_la_tela_vuelve_a_quedar_por_pedir(self):
        self.op.refresh_from_db()
        self.assertEqual(self.op.tela, 'Pedida')
        self.assertEqual(self.anular(motivo='  ').status_code, 400)
        r = self.anular()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['estado'], r.data['motivo_anulacion'], r.data['anulado_por_nombre']),
                         ('Anulado', 'Se pidió con el color equivocado', self.admin.first_name))
        self.pedido.refresh_from_db()
        self.assertIsNotNone(self.pedido.anulado_en)
        self.assertEqual(self.pedido.detalles.count(), 1)  # no se borra nada
        self.assertTrue(RegistroAuditoria.objects.filter(accion='pedido_tela.anulado', objeto_id=str(self.pedido.pk)).exists())
        self.op.refresh_from_db()
        self.assertEqual(self.op.tela, 'Por pedir')
        d = self.api_asesor.get(self.url).data
        self.assertEqual(d['lineas'][0]['tela_pedidos'], [])
        # La tela se puede volver a pedir.
        self.assertEqual(self.pedir_telas(d).status_code, 201)
        # Un pedido anulado ya no cambia de estado.
        r = self.api_admin.patch(f'/api/pedidos-telas/{self.pedido.pk}/', {'estado': 'Pendiente'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.anular().status_code, 400)

    def test_editar_estado_sin_el_permiso_de_anular_no_anula(self):
        self.permisos('auxiliar', ['VER_PEDIDOS_TELAS', 'VER_TODOS_PEDIDOS_TELAS', 'EDITAR_ESTADO_TELA_ORDEN'])
        auxiliar = self.api(self.crear_usuario('aux_telas', 'auxiliar'))
        self.assertEqual(self.anular(cliente=auxiliar).status_code, 403)
        # El resto de estados sí los puede cambiar.
        r = auxiliar.patch(f'/api/pedidos-telas/{self.pedido.pk}/', {'estado': 'En Lottus'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.permisos('administrador', ['VER_PEDIDOS_TELAS', 'VER_TODOS_PEDIDOS_TELAS', 'EDITAR_ESTADO_TELA_ORDEN'])
        self.assertEqual(self.anular().status_code, 403)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'En Lottus')

    def test_la_migracion_lo_habilita_solo_al_administrador(self):
        migracion = import_module('ordenes.migrations.0082_anular_pedido_tela')
        self.permisos('administrador', ['VER_PEDIDOS_TELAS'])
        self.permisos('auxiliar', ['VER_PEDIDOS_TELAS', 'EDITAR_ESTADO_TELA_ORDEN'])
        editor = type('E', (), {'connection': connection})()
        migracion.habilitar_administrador(apps, editor)
        migracion.habilitar_administrador(apps, editor)  # repetirla no duplica
        self.assertEqual(RolePermission.objects.get(role='administrador').permissions, ['VER_PEDIDOS_TELAS', 'ANULAR_PEDIDO_TELA'])
        self.assertNotIn('ANULAR_PEDIDO_TELA', RolePermission.objects.get(role='auxiliar').permissions)
