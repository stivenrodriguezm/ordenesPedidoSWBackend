"""Correo persistente y validación de imágenes (H30 · P07-06)."""
import io
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from PIL import Image

from ordenes.tests.utils import LottusTestCase
from paginaweb.models import CorreoSaliente, PqrsTicket


def png(lado=10):
    buf = io.BytesIO()
    Image.new('RGB', (lado, lado), 'white').save(buf, 'PNG')
    return buf.getvalue()


class PqrsCorreoTests(LottusTestCase):
    payload = {'tipo': 'peticion', 'asunto': 'x', 'nombre': 'Ficticio', 'email': 'ficticio@example.invalid',
               'telefono': '000', 'mensaje': 'Mensaje de prueba'}

    def test_registro_y_envio(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post('/api/paginaweb/pqrs/', self.payload, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(PqrsTicket.objects.count(), 1)
        self.assertEqual(CorreoSaliente.objects.filter(estado='enviado').count(), 2)
        self.assertEqual(len(mail.outbox), 2)

    def test_fallo_smtp_no_finge_entrega_y_se_reintenta(self):
        with mock.patch('paginaweb.emails.EmailMultiAlternatives.send', side_effect=OSError('smtp caído')):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post('/api/paginaweb/pqrs/', self.payload, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['correo_confirmacion'], 'pendiente')
        self.assertEqual(PqrsTicket.objects.count(), 1)  # la PQRS queda registrada
        self.assertEqual(CorreoSaliente.objects.filter(estado='fallido').count(), 2)
        call_command('reintentar_correos', stdout=io.StringIO())
        self.assertEqual(CorreoSaliente.objects.filter(estado='enviado').count(), 2)


class SubidaImagenesTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')

    def subir(self, archivo):
        return self.api(self.admin).post('/api/listaprecios/upload-foto/', {'images': archivo}, format='multipart')

    def test_archivo_falso_con_extension_de_imagen(self):
        r = self.subir(SimpleUploadedFile('foto.jpg', b'<html>no soy imagen</html>', content_type='image/jpeg'))
        self.assertEqual(r.status_code, 400)

    def test_imagen_sobredimensionada_y_pesada(self):
        from paginaweb.image_utils import InvalidImageError, validar_archivo_imagen
        with self.assertRaises(InvalidImageError):
            validar_archivo_imagen(SimpleUploadedFile('g.png', png(10)), max_lado=5)
        with self.assertRaises(InvalidImageError):
            validar_archivo_imagen(SimpleUploadedFile('p.png', png(10)), max_bytes=10)

    def test_imagen_valida_se_sube(self):
        with mock.patch('listaprecios.views.upload_to_sirv', return_value='https://cdn.invalid/x.png') as subir:
            r = self.subir(SimpleUploadedFile('ok.png', png(), content_type='image/png'))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(subir.call_args[0][2], 'image/png')


class FichaWebTests(LottusTestCase):
    def test_cuatro_campos_persisten_y_precios_no_se_publican(self):
        from paginaweb.models import PaginawebProducto
        admin = self.crear_usuario('editor-web', 'administrador')
        producto = PaginawebProducto.objects.create(name='Ficha', slug='ficha', price='12345', old_price='99999',
            variants=[{'id': 'opcion', 'label': '3 puestos', 'priceAbsolute': 999, 'priceDelta': 500}])
        campos = {'shortDescription': '**Resumen**', 'description': '## Diseño\n\n- Confort\n---\nTexto',
                  'characteristics': '1. Reclinable\n2. Amplio', 'materials': '**Madera** y *tela*'}
        r = self.api(admin).patch(f'/api/paginaweb/admin/products/{producto.pk}/', {**campos, 'price': 0}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        producto.refresh_from_db()
        self.assertEqual(producto.price, 12345)
        for url in ('/api/paginaweb/products/ficha/', '/api/paginaweb/products/'):
            respuesta = self.client.get(url).json()
            p = respuesta.get('product') or respuesta['products'][0]
            for campo, valor in campos.items():
                self.assertEqual(p[campo], valor)
            self.assertNotIn('price', str(p).lower())
            self.assertEqual(p['variants'][0]['label'], '3 puestos')

    def test_migracion_conserva_caracteristicas_y_dimensiones_previas(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from paginaweb.models import PaginawebProducto
        p = PaginawebProducto.objects.create(name='Ficha anterior', slug='anterior', features=['Espaldar alto', 'Reclinable'], dimensions='200 × 90 cm')
        migracion = import_module('paginaweb.migrations.0005_caracteristicas_con_formato')
        migracion.copiar_a_caracteristicas(apps, type('Editor', (), {'connection': connection})())
        p.refresh_from_db()
        self.assertEqual(p.characteristics, '- Espaldar alto\n- Reclinable\n\n**Dimensiones:** 200 × 90 cm')
        p.characteristics = 'Edición nueva'
        p.save()
        migracion.copiar_a_caracteristicas(apps, type('Editor', (), {'connection': connection})())
        p.refresh_from_db()
        self.assertEqual(p.characteristics, 'Edición nueva')
