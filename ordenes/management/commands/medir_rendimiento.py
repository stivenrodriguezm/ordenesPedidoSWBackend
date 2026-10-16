"""Medición de SOLO LECTURA de las consultas que hacen las pantallas (P08-01).

Uso (sobre una copia autorizada o datos sintéticos, nunca como carga sobre
producción):
    python manage.py medir_rendimiento (--usuario <username> | --rol <rol>) [--repeticiones 5]
        [--solo grupos] [--json]

Por cada endpoint GET registra: estado HTTP, número de consultas SQL, bytes de
la respuesta y latencia mediana/p95 del proceso completo (incluye la ida y
vuelta a la base). Cada petición corre dentro de una transacción que se
revierte. No imprime contenido de las respuestas. La latencia depende del
equipo y de la distancia a la base: compare solo mediciones hechas en las
mismas condiciones (mismo equipo, misma base, mismo usuario).
"""
import json
import platform
import statistics
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext, override_settings
from rest_framework.test import APIClient

# (nombre, ruta) de las cargas iniciales de cada pantalla.
ENDPOINTS = [
    ('inventario', '/api/suministros/inventario/'),
    ('grupos', '/api/suministros/grupos/'),
    ('facturas', '/api/suministros/facturas/'),
    ('facturas_full', '/api/suministros/facturas/?full=true'),
    ('remisiones', '/api/suministros/remisiones/'),
    ('ventas', '/api/ventas/?page=1&page_size=20'),
    ('clientes_appcontext', '/api/clientes/?page_size=1000'),
    ('clientes_pagina', '/api/clientes/?page=1&page_size=20'),
    ('proveedores', '/api/proveedores/'),
    ('referencias', '/api/referencias/'),
    ('ordenes', '/api/listar-pedidos/'),
    ('caja', '/api/caja/?page=1&page_size=20'),
    ('recibos', '/api/recibos-caja/?page=1&page_size=20'),
    ('egresos', '/api/comprobantes-egreso/?page=1&page_size=20'),
    ('dashboard', '/api/dashboard-stats/'),
    ('lista_precios', '/api/listaprecios/lineas/'),
    ('usuario', '/api/user/'),
    ('remision_inventario', '/api/suministros/remisiones/inventario-disponible/'),
    ('remision_ventas', '/api/suministros/remisiones/ventas-disponibles/'),
    ('remision_catalogo', '/api/suministros/remisiones/catalogo/'),
    ('pendientes_ids', '/api/get-pendientes-ids/'),
    ('pedidos_telas', '/api/pedidos-telas/'),
    ('proveedores_telas', '/api/proveedores-telas/'),
    ('direcciones', '/api/direcciones-entrega/'),
    ('vendedores', '/api/vendedores/'),
    ('transportadores', '/api/transportadores/'),
    ('usuarios', '/api/usuarios/?page=1'),
    ('categorias', '/api/suministros/categorias/'),
    ('subcategorias', '/api/suministros/subcategorias/'),
    ('sedes', '/api/suministros/sedes/?page_size=1000'),
    ('zonas', '/api/suministros/zonas/?page_size=1000'),
    ('ordenes_pedido', '/api/ordenes-pedido/'),
    ('lp_catalogo', '/api/listaprecios/catalogo/'),
    ('lp_categorias', '/api/listaprecios/categorias/'),
    ('lp_multiplicadores', '/api/listaprecios/multiplicadores/'),
    ('lp_grupos_tela', '/api/listaprecios/grupos-tela/'),
    ('web_productos', '/api/paginaweb/admin/products/'),
    ('web_pqrs', '/api/paginaweb/admin/pqrs/'),
    ('web_asesores', '/api/paginaweb/admin/asesores/'),
    ('chart', '/api/sales-chart-data/'),
    ('actividad', '/api/vendedor-recent-activity/'),
    ('role_permissions', '/api/role-permissions/'),
]
# Las primeras 17 son la línea base inicial (evidencia/p08-linea-base-rendimiento.txt).


class _Revertir(Exception):
    pass


def percentil(valores, p):
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, round(p / 100 * (len(ordenados) - 1))))
    return ordenados[k]


class Command(BaseCommand):
    help = 'Mide consultas, tamaño y latencia de los GET de las pantallas (solo lectura).'

    def add_arguments(self, parser):
        grupo = parser.add_mutually_exclusive_group(required=True)
        grupo.add_argument('--usuario')
        grupo.add_argument('--rol', help='usa el primer usuario activo de ese rol')
        parser.add_argument('--repeticiones', type=int, default=5)
        parser.add_argument('--solo', nargs='*', default=None)
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **opts):
        usuarios = get_user_model().objects.filter(is_active=True).order_by('id')
        if opts['usuario']:
            usuario = usuarios.filter(username=opts['usuario']).first()
        else:
            usuario = usuarios.filter(role=opts['rol']).first()
        if usuario is None:
            raise CommandError('Usuario no encontrado.')
        endpoints = [e for e in ENDPOINTS if not opts['solo'] or e[0] in opts['solo']]
        cliente = APIClient()
        cliente.force_authenticate(usuario)
        # Caché local: las mediciones no consumen la cuota de peticiones del
        # usuario ni escriben en la caché compartida del servidor.
        with override_settings(
            ALLOWED_HOSTS=['testserver'],
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
        ):
            resultados = [self._medir(cliente, nombre, ruta, opts['repeticiones']) for nombre, ruta in endpoints]
        salida = {
            'equipo': f'{platform.system()} {platform.machine()} / Python {platform.python_version()}',
            'base': connection.vendor,
            'rol': usuario.role,
            'repeticiones': opts['repeticiones'],
            'resultados': resultados,
        }
        if opts['json']:
            self.stdout.write(json.dumps(salida, indent=2))
            return
        self.stdout.write(f"{salida['equipo']} · base {salida['base']} · rol {salida['rol']} · n={salida['repeticiones']}")
        self.stdout.write(f"{'endpoint':<22}{'http':>5}{'consultas':>10}{'KB':>10}{'mediana ms':>12}{'p95 ms':>9}")
        for r in resultados:
            self.stdout.write(
                f"{r['endpoint']:<22}{r['http']:>5}{r['consultas']:>10}{r['kb']:>10}{r['mediana_ms']:>12}{r['p95_ms']:>9}"
            )

    def _medir(self, cliente, nombre, ruta, repeticiones):
        tiempos, consultas, tamano, estado = [], 0, 0, None
        for _ in range(max(1, repeticiones)):
            try:
                with transaction.atomic():
                    with CaptureQueriesContext(connection) as ctx:
                        inicio = time.perf_counter()
                        respuesta = cliente.get(ruta)
                        tiempos.append((time.perf_counter() - inicio) * 1000)
                    estado = respuesta.status_code
                    consultas = len(ctx.captured_queries)
                    tamano = len(respuesta.content)
                    raise _Revertir()
            except _Revertir:
                pass
        return {
            'endpoint': nombre,
            'ruta': ruta,
            'http': estado,
            'consultas': consultas,
            'kb': round(tamano / 1024, 1),
            'mediana_ms': round(statistics.median(tiempos)),
            'p95_ms': round(percentil(tiempos, 95)),
        }
