"""Correo persistente y validación de imágenes (H30 · P07-06)."""
import io
import json
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from PIL import Image

from ordenes.tests.utils import LottusTestCase
from paginaweb.models import AsesorPerfil, CorreoSaliente, PaginawebProducto, PqrsTicket, VisitaWeb


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


@override_settings(CLOUDINARY_CLOUD_NAME='cuenta-prueba')
class FotoAsesorTests(LottusTestCase):
    """La foto que devuelve el cargador (Cloudinary) debe poder guardarse en el perfil."""
    url_cloudinary = 'https://res.cloudinary.com/cuenta-prueba/image/upload/f_auto,q_auto/v1/asesores/x.png'

    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.asesor = AsesorPerfil.objects.create(id='a1', nombre='Asesor Ficticio', slug='asesor-ficticio')

    def guardar_foto(self, foto):
        return self.api(self.admin).patch(f'/api/paginaweb/admin/asesores/{self.asesor.id}/', {'foto': foto}, format='json')

    def test_subir_y_guardar_foto(self):
        with mock.patch('paginaweb.views.upload_to_cloudinary', return_value=self.url_cloudinary):
            r = self.api(self.admin).post('/api/paginaweb/admin/asesores/upload-foto/',
                                          {'foto': SimpleUploadedFile('ok.png', png(), content_type='image/png')},
                                          format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        r = self.guardar_foto(r.data['url'])
        self.assertEqual(r.status_code, 200, r.data)
        self.asesor.refresh_from_db()
        self.assertEqual(self.asesor.foto, self.url_cloudinary)

    def test_fotos_antiguas_y_vacia_se_aceptan(self):
        self.assertEqual(self.guardar_foto('/media/asesores/vieja.jpg').status_code, 200)
        self.assertEqual(self.guardar_foto('').status_code, 200)

    def test_url_ajena_se_rechaza(self):
        for foto in ('https://ejemplo.invalid/asesores/x.png',
                     'https://res.cloudinary.com/otra-cuenta/image/upload/v1/asesores/x.png',
                     'https://res.cloudinary.com/cuenta-prueba/image/upload/v1/paginaweb/x.png'):
            self.assertEqual(self.guardar_foto(foto).status_code, 400, foto)


class VisitasWebTests(LottusTestCase):
    """Contador de visitas de la web y la landing (2026-11-04)."""
    UA_CEL = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1'
    UA_PC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'

    def registrar(self, ua=UA_CEL, texto=False, **datos):
        cuerpo = {'sitio': 'web', 'tipo': 'pagina', 'ruta': '/', 'visitante': 'visitante-0001', 'sesion': 'sesion-0001', **datos}
        return self.client.post('/api/paginaweb/visitas/', json.dumps(cuerpo),
                                content_type='text/plain' if texto else 'application/json', HTTP_USER_AGENT=ua)

    def test_registra_entrada_con_fuente_y_dispositivo(self):
        r = self.registrar(texto=True, ruta='/producto/sofa-roma', entrada=True, nuevo=True,
                           referente='https://l.instagram.com/?u=x')
        self.assertEqual(r.status_code, 204, r.content)
        v = VisitaWeb.objects.get()
        self.assertEqual((v.ruta, v.etiqueta, v.fuente, v.dispositivo, v.entrada, v.visitante_nuevo),
                         ('/producto', 'sofa-roma', 'instagram', 'celular', True, True))

    def test_rutas_fuentes_y_clics(self):
        self.registrar(ruta='/catalogo.html', entrada=True, referente='https://landing.muebleslottus.com/')
        self.registrar(ruta='/index.html', entrada=True, referente='https://muebleslottus.com/sora', sesion='sesion-0002')
        self.registrar(sitio='landing', entrada=True, utm='Instagram', sesion='sesion-0003', ua=self.UA_PC)
        self.registrar(sitio='landing', tipo='clic', etiqueta='WhatsApp-Cotizar', sesion='sesion-0003')
        filas = list(VisitaWeb.objects.order_by('id').values_list('ruta', 'fuente', 'etiqueta', 'dispositivo'))
        self.assertEqual(filas, [('/catalogo', 'landing', '', 'celular'), ('/', 'interna', '', 'celular'),
                                 ('/', 'instagram', '', 'computador'), ('/', '', 'whatsapp-cotizar', 'celular')])

    def test_rechaza_invalidos_e_ignora_bots(self):
        self.assertEqual(self.registrar(sitio='otro').status_code, 400)
        self.assertEqual(self.registrar(visitante='x').status_code, 400)
        self.assertEqual(self.registrar(tipo='clic').status_code, 400)
        self.assertEqual(self.registrar(ua='Mozilla/5.0 HeadlessChrome/126').status_code, 204)
        self.assertEqual(self.registrar(ua='Googlebot/2.1').status_code, 204)
        self.assertFalse(VisitaWeb.objects.exists())

    def test_resumen_requiere_permiso_y_suma_por_sitio(self):
        vendedor = self.crear_usuario('vendedor-web')
        self.assertEqual(self.api(vendedor).get('/api/paginaweb/admin/visitas/').status_code, 403)
        producto = PaginawebProducto.objects.create(id='p1', name='Sofá Roma', slug='sofa-roma')
        self.registrar(ruta='/producto/sofa-roma', entrada=True, nuevo=True)
        self.registrar(ruta='/producto/sofa-roma')
        self.registrar(tipo='clic', etiqueta='whatsapp')
        self.registrar(sitio='landing', entrada=True, visitante='visitante-0002', sesion='sesion-0002', ua=self.UA_PC)
        r = self.api(self.crear_usuario('admin-web', role='administrador')).get('/api/paginaweb/admin/visitas/?dias=30')
        self.assertEqual(r.status_code, 200, r.content)
        web, landing = r.data['totales']['web'], r.data['totales']['landing']
        self.assertEqual((web['visitas'], web['sesiones'], web['visitantes'], web['nuevos'], web['clics_whatsapp']), (2, 1, 1, 1, 1))
        self.assertEqual((landing['visitas'], landing['visitantes']), (1, 1))
        self.assertEqual(r.data['historico'], {'landing': 1, 'web': 2})
        self.assertEqual(r.data['productos'][0]['nombre'], producto.name)
        self.assertEqual(r.data['dispositivos']['landing'], [{'clave': 'computador', 'n': 1}])
        self.assertEqual(len(r.data['por_dia']), 30)
        self.assertEqual(r.data['por_dia'][-1]['web']['visitas'], 2)

    def test_resumen_valida_rango(self):
        admin = self.crear_usuario('admin-web', role='administrador')
        self.assertEqual(self.api(admin).get('/api/paginaweb/admin/visitas/?desde=2026-05-01&hasta=2026-04-01').status_code, 400)
        self.assertEqual(self.api(admin).get('/api/paginaweb/admin/visitas/?desde=2024-01-01&hasta=2026-04-01').status_code, 400)
