"""Escenario P14 ficticio, explícitamente rechazado en cualquier otro perfil."""
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from ordenes.models import CustomUser, RolePermission, Cliente, Venta, Proveedor, Referencia
from suministros.models import Inventario, Sede, Zona

CLAVE_DEMO = 'Demo-local-P14-2026!'


class Command(BaseCommand):
    help = 'Crea datos ficticios solo en settings_aceptacion. No modifica ni borra una base con usuarios.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'ACEPTACION_LOCAL', False) or settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('Solo se permite el perfil local desechable settings_aceptacion.')
        if CustomUser.objects.exists():
            raise CommandError('El escenario ya tiene usuarios. Usa otra carpeta temporal; no se borra nada.')
        for rol, permisos in {
            'vendedor': ['VER_CLIENTES', 'EXPORTAR_CLIENTES', 'VER_PROPIAS_VENTAS', 'VER_PRECIOS_VENTA', 'VER_RECIBOS', 'VER_INVENTARIO'],
            'auxiliar': ['VER_CAJA', 'CERRAR_CAJA', 'VER_RECIBOS', 'CREAR_RECIBO', 'VER_CLIENTES', 'VER_INVENTARIO'],
            'bodega': ['VER_INVENTARIO'],
            'transportador': ['VER_REMISIONES', 'CAMBIAR_ESTADO_REMISION'],
        }.items():
            RolePermission.objects.update_or_create(role=rol, defaults={'permissions': permisos})
        usuarios = {}
        for nombre, rol in [('admin', 'administrador'), ('vendedor', 'vendedor'), ('ajeno', 'vendedor'), ('caja', 'auxiliar'), ('bodega', 'bodega'), ('transporte', 'transportador')]:
            usuarios[nombre] = CustomUser.objects.create_user(username='demo_' + nombre, password=CLAVE_DEMO, first_name='DEMO ' + nombre, role=rol)
        sede = Sede.objects.create(nombre='Sede ficticia P14')
        zona = Zona.objects.create(nombre='Zona ficticia', sede=sede)
        proveedor = Proveedor.objects.create(nombre_empresa='Proveedor FICTICIO P14')
        referencia = Referencia.objects.create(nombre='Silla DEMO', proveedor=proveedor)
        for n in range(37):
            cliente = Cliente.objects.create(nombre=f'Cliente FICTICIO {n:02}', cedula=f'DEMO-{n:04}', telefono1='0000000000', correo='demo@example.invalid')
            # Mantener la sede dentro de las opciones operativas que consume la
            # pantalla de ventas; ``CENTRO`` queda reservado para datos
            # históricos y pruebas de compatibilidad.
            venta = Venta.objects.create(id=14000+n, cliente=cliente, vendedor=usuarios['vendedor' if n % 2 == 0 else 'ajeno'], valor_total='1000.25', abono='0', saldo='1000.25', fecha_venta=date(2026, 10, 6), fecha_entrega=date(2026, 10, 10), sede='Lottus 1')
            if n == 1:
                venta.vendedores_compartidos.add(usuarios['vendedor'])
        Inventario.objects.create(id_referencia='DEMO-001', referencia=referencia, zona=zona, costo_especifico='100.25')
        from listaprecios.models import CategoriaLista, LineaProducto, VarianteProducto, GrupoTela, CargoVariante
        categoria = CategoriaLista.objects.create(nombre='Sala DEMO', slug='sala-demo-p15')
        coleccion = LineaProducto.objects.create(nombre='Colección DEMO', slug='coleccion-demo-p15')
        variante = VarianteProducto.objects.create(linea=coleccion, categoria=categoria, nombre='Sofá 3 puestos', costo_base=100, metraje_tela=2)
        GrupoTela.objects.get_or_create(nombre='Grupo DEMO', defaults={'precio_por_metro': 15})
        CargoVariante.objects.create(variante=variante, descripcion='Patas especiales DEMO', valor=10, opcional=True)
        permisos = RolePermission.objects.get(role='vendedor')
        permisos.permissions += ['EDITAR_PRODUCTOS_VENTA', 'CREAR_PROPIAS_ORDENES', 'VER_ORDENES', 'CREAR_REMISION', 'VER_REMISIONES']
        permisos.save(update_fields=['permissions'])
        self.stdout.write('Escenario FICTICIO listo: 6 usuarios demo_*, 37 clientes/ventas, 1 unidad y catálogo de productos DEMO.')
        self.stdout.write('Clave pública de demostración local: ' + CLAVE_DEMO)
