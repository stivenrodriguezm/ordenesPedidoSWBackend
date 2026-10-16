"""Consultas por petición que no crecen con los datos (P08-01/P08-04, H26).

Medido sobre la copia de producción: grupos hacía 140 consultas (~13 s),
facturas?full=true 1961 (~198 s), subcategorias 68 (~6 s) y ordenes-pedido 72
(~6 s) porque cada fila consultaba sus relaciones.
Cada prueba compara el número de consultas con 2 y con 6 filas: debe ser el
mismo."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from ordenes.models import DetallePedido, DetallePedidoTela, OrdenPedido, PedidoTela, ProveedorTela
from ordenes.tests.utils import LottusTestCase
from suministros.models import (
    Categoria, FacturaProveedor, GrupoInventario, GrupoInventarioComponente, Inventario,
    ItemInventarioTelaCuero, Sede, Subcategoria, Zona,
)


class ConsultasAcotadasTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.vendedor = self.crear_usuario('vend', last_name='Uno')
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov)
        self.cat = Categoria.objects.create(nombre='Sala')
        self.sub = Subcategoria.objects.create(categoria=self.cat, nombre='Sofá')
        self.zona = Zona.objects.create(sede=Sede.objects.create(nombre='Sede ficticia'), nombre='Piso 1')
        self.n = 0

    def _fila(self):
        """Un grupo con componente y dos ítems, en una factura propia."""
        self.n += 1
        grupo = GrupoInventario.objects.create(nombre=f'Grupo {self.n}', categoria=self.cat, subcategoria=self.sub)
        GrupoInventarioComponente.objects.create(grupo=grupo, referencia=self.ref, categoria=self.cat, subcategoria=self.sub)
        factura = FacturaProveedor.objects.create(id_manual=f'F-{self.n}', proveedor=self.prov, valor='300')
        venta = self.venta(self.vendedor)
        venta.vendedores_compartidos.add(self.crear_usuario(f'comp{self.n}'))
        for k, costo in enumerate(('100', '200')):
            item = Inventario.objects.create(
                id_referencia=f'REND{self.n}-{k}', referencia=self.ref, categoria=self.cat, subcategoria=self.sub,
                costo_especifico=costo, grupo=grupo, factura=factura, zona=self.zona, venta=venta,
            )
            ItemInventarioTelaCuero.objects.create(inventario=item, costo_unidad='10', cantidad='2')
        Subcategoria.objects.create(categoria=Categoria.objects.create(nombre=f'Cat {self.n}'), nombre=f'Sub {self.n}')
        orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.vendedor, venta=venta, fecha_esperada='2026-12-01')
        DetallePedido.objects.create(orden=orden, referencia=self.ref, cantidad=1, especificaciones='-')
        pedido = PedidoTela.objects.create(
            id=self.n, usuario=self.vendedor, orden_asociada=orden, direccion_entrega='-',
            proveedor=ProveedorTela.objects.get_or_create(nombre_empresa='Telas ficticias')[0],
        )
        DetallePedidoTela.objects.create(pedido=pedido, tela='Lino', cantidad='3')

    def _consultas(self, ruta):
        cliente = self.api(self.admin)
        with CaptureQueriesContext(connection) as ctx:
            r = cliente.get(ruta)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return len(ctx.captured_queries), r

    def _no_crece(self, ruta):
        for _ in range(2):
            self._fila()
        pocas, _ = self._consultas(ruta)
        for _ in range(4):
            self._fila()
        muchas, r = self._consultas(ruta)
        self.assertEqual(pocas, muchas, f'{ruta}: {pocas} consultas con 2 filas y {muchas} con 6')
        return r

    def test_grupos_no_consulta_por_grupo(self):
        r = self._no_crece('/api/suministros/grupos/')
        grupo = next(g for g in r.data if g['nombre'] == 'Grupo 1')
        self.assertEqual(grupo['items_count'], 2)
        self.assertEqual(Decimal(str(grupo['costo_total'])), Decimal('300'))
        self.assertEqual(grupo['categoria_nombre'], 'Sala')
        self.assertEqual(grupo['subcategoria_nombre'], 'Sofá')
        self.assertEqual(grupo['componentes'][0]['referencia_nombre'], self.ref.nombre)

    def test_facturas_full_no_consulta_por_item(self):
        r = self._no_crece('/api/suministros/facturas/?full=true')
        filas = r.data['results'] if isinstance(r.data, dict) else r.data
        factura = next(f for f in filas if f['id_manual'] == 'F-1')
        item = factura['items_inventario'][0]
        self.assertEqual(item['grupo_nombre'], 'Grupo 1')
        self.assertEqual(item['grupo_categoria_nombre'], 'Sala')
        self.assertEqual(item['zona_nombre'], 'Piso 1')
        self.assertEqual(len(item['telas_cueros']), 1)
        self.assertIn(' y ', item['vendedor_nombre'])

    def test_subcategorias_no_consulta_por_fila(self):
        r = self._no_crece('/api/suministros/subcategorias/')
        self.assertIn('Cat 1', [x['categoria_nombre'] for x in r.data])

    def test_ordenes_pedido_no_consulta_por_orden(self):
        r = self._no_crece('/api/ordenes-pedido/')
        filas = r.data['results']
        self.assertEqual([f['id'] for f in filas], sorted((f['id'] for f in filas), reverse=True))
        self.assertEqual(filas[0]['detalles'][0]['referencia_nombre'], self.ref.nombre)
        self.assertEqual(filas[0]['telas_asociadas'][0]['tela'], 'Lino')
        self.assertEqual(filas[0]['vendedor'], 'vend')
