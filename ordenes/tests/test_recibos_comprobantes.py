"""Recibos de caja (2026-10-28): número automático desde 10100, fotos de comprobantes
comprimidas y el vendedor puede crear recibos de sus ventas."""
import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from ordenes.models import ComprobanteReciboCaja, ReciboCaja
from ordenes.recibos_comprobantes import LADO_MAXIMO, comprimir_comprobante
from ordenes.tests.utils import LottusTestCase

URL = 'https://res.cloudinary.com/lottus-test/image/upload/f_auto,q_auto/recibos_caja/foto_{}.jpg'


def imagen(formato='PNG', tamano=(3000, 1500), modo='RGB'):
    buf = io.BytesIO()
    Image.new(modo, tamano, (20, 120, 200) if modo == 'RGB' else (20, 120, 200, 128)).save(buf, format=formato)
    return buf.getvalue()


@override_settings(CLOUDINARY_CLOUD_NAME='lottus-test')
class RecibosComprobantesTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin_rc', role='administrador')
        self.vendedor = self.crear_usuario('vend_rc', role='vendedor')
        self.otro = self.crear_usuario('vend_otro', role='vendedor')
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS', 'ACCESO_RECIBOS', 'CREAR_RECIBO'])
        self.v = self.venta(self.vendedor)
        self.ajena = self.venta(self.otro)

    def crear(self, usuario, **datos):
        cuerpo = {'venta': self.v.id, 'pagos': [{'metodo_pago': 'Davivienda', 'valor': '100'}], **datos}
        return self.api(usuario).post('/api/recibos-caja/crear/', cuerpo, format='json')

    def test_numero_automatico_desde_10100_de_uno_en_uno(self):
        self.assertEqual(self.api(self.admin).get('/api/recibos-caja/siguiente-numero/').data['numero'], 10100)
        r1 = self.crear(self.admin, numero_automatico=True)
        r2 = self.crear(self.admin, numero_automatico=True, id=55)  # el id manual se ignora
        self.assertEqual((r1.status_code, r1.data['id']), (201, 10100))
        self.assertEqual((r2.status_code, r2.data['id']), (201, 10101))
        # Los manuales siguen con su número; uno escrito a mano en la serie se salta.
        self.assertEqual(self.crear(self.admin, id=4800).data['id'], 4800)
        self.assertEqual(self.crear(self.admin, id=10102).status_code, 201)
        self.assertEqual(self.api(self.admin).get('/api/recibos-caja/siguiente-numero/').data['numero'], 10103)
        self.assertEqual(self.crear(self.admin, numero_automatico=True).data['id'], 10103)

    def test_manual_valida_el_numero(self):
        self.assertEqual(self.crear(self.admin).status_code, 400)  # sin número ni automático
        self.assertEqual(self.crear(self.admin, id='RC-1').status_code, 400)
        self.assertEqual(self.crear(self.admin, id=700).status_code, 201)
        self.assertEqual(self.crear(self.admin, id=700).status_code, 400)  # repetido

    def test_vendedor_crea_recibo_de_su_venta_con_foto(self):
        r = self.crear(self.vendedor, numero_automatico=True, comprobantes=[URL.format(1)])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([c['url'] for c in r.data['comprobantes']], [URL.format(1)])
        self.assertEqual(ComprobanteReciboCaja.objects.get().subido_por, self.vendedor)
        # No puede crear sobre ventas ajenas y solo ve los recibos de sus ventas.
        self.assertEqual(self.crear(self.vendedor, numero_automatico=True, venta=self.ajena.id).status_code, 404)
        ReciboCaja.objects.create(id=9001, venta=self.ajena)
        ids = [x['id'] for x in self.api(self.vendedor).get('/api/recibos-caja/').data['results']]
        self.assertEqual(ids, [r.data['id']])

    def test_la_foto_es_opcional_y_solo_de_la_plataforma(self):
        self.assertEqual(self.crear(self.admin, id=801).status_code, 201)
        r = self.crear(self.admin, id=802, comprobantes=['https://otro-sitio.com/recibos_caja/x.jpg'])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ReciboCaja.objects.filter(id=802).exists())

    def test_agregar_y_quitar_fotos_de_un_recibo(self):
        rc = self.crear(self.vendedor, id=900).data
        r = self.api(self.vendedor).post(f"/api/recibos-caja/{rc['id']}/comprobantes/", {'comprobantes': [URL.format(2), URL.format(3)]}, format='json')
        self.assertEqual((r.status_code, len(r.data['comprobantes'])), (200, 2))
        # Recibo de una venta ajena: no lo encuentra.
        ReciboCaja.objects.create(id=9002, venta=self.ajena)
        r = self.api(self.vendedor).post('/api/recibos-caja/9002/comprobantes/', {'comprobantes': [URL.format(4)]}, format='json')
        self.assertEqual(r.status_code, 404)
        # Quitar fotos requiere EDITAR_RECIBO (el vendedor no lo tiene; el administrador sí).
        foto = ComprobanteReciboCaja.objects.filter(recibo_id=rc['id']).first()
        self.assertEqual(self.api(self.vendedor).delete(f'/api/recibos-caja/comprobantes/{foto.pk}/').status_code, 403)
        self.assertEqual(self.api(self.admin).delete(f'/api/recibos-caja/comprobantes/{foto.pk}/').status_code, 204)
        self.assertEqual(ComprobanteReciboCaja.objects.filter(recibo_id=rc['id']).count(), 1)

    def test_subir_comprime_la_foto_antes_de_enviarla(self):
        archivo = SimpleUploadedFile('pantallazo.png', imagen(), content_type='image/png')
        with mock.patch('paginaweb.cloudinary_client.upload_to_cloudinary', return_value=URL.format(9)) as subir:
            r = self.api(self.vendedor).post('/api/recibos-caja/comprobantes/subir/', {'imagen': archivo}, format='multipart')
        self.assertEqual((r.status_code, r.data['url']), (200, URL.format(9)))
        datos, nombre, tipo = subir.call_args.args
        self.assertTrue(nombre.startswith('recibos_caja/') and nombre.endswith('.jpg'))
        self.assertEqual(tipo, 'image/jpeg')
        with Image.open(io.BytesIO(datos)) as img:
            self.assertEqual((img.format, max(img.size)), ('JPEG', LADO_MAXIMO))
        malo = SimpleUploadedFile('x.png', b'no es imagen', content_type='image/png')
        r = self.api(self.vendedor).post('/api/recibos-caja/comprobantes/subir/', {'imagen': malo}, format='multipart')
        self.assertEqual(r.status_code, 400)
        # Sin crear ni editar recibos no se sube nada.
        self.permisos('vendedor', ['VER_PROPIAS_VENTAS'])
        r = self.api(self.vendedor).post('/api/recibos-caja/comprobantes/subir/', {'imagen': archivo}, format='multipart')
        self.assertEqual(r.status_code, 403)

    def test_compresion_de_transparencia_y_fotos_pequenas(self):
        datos = comprimir_comprobante(imagen('PNG', (400, 300), 'RGBA'))
        with Image.open(io.BytesIO(datos)) as img:
            self.assertEqual((img.format, img.size), ('JPEG', (400, 300)))
