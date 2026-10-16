"""Oficina IA: zonas reales y conversaciones privadas separadas por perfil."""
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.db import connection

from django.utils import timezone
from ordenes.models import ConversacionAsistente, MensajeAsistente, PerfilAsistente, ZonaOficinaIA
from ordenes.tests.utils import LottusTestCase


class OficinaIATests(LottusTestCase):
    def setUp(self):
        self.gerente = self.crear_usuario('gerente_oficina', 'administrador')
        self.vendedor = self.crear_usuario('vendedor_oficina')
        self.permisos('vendedor', ['USAR_ASISTENTE_IA'])
        self.admin = self.api(self.gerente)
        self.lector = self.api(self.vendedor)
        self.zona = ZonaOficinaIA.objects.create(nombre='Estudio de prueba', ambiente='estudio')
        self.perfil = PerfilAsistente.objects.create(nombre='Perfil de prueba', rol='Asesor',
            instrucciones='Instrucciones de prueba suficientemente largas para validar el perfil.', areas=['ventas'], zona=self.zona)

    def test_zonas_se_consultan_y_solo_gestor_las_modifica(self):
        self.assertEqual(self.lector.get('/api/asistente/zonas/').status_code, 200)
        for api in [self.lector]:
            self.assertEqual(api.post('/api/asistente/zonas/', {'nombre':'Nueva'}, format='json').status_code, 403)
            self.assertEqual(api.patch(f'/api/asistente/zonas/{self.zona.pk}/', {'nombre':'Cambio'}, format='json').status_code, 403)
            self.assertEqual(api.patch(f'/api/asistente/perfiles/{self.perfil.pk}/', {'zona':None}, format='json').status_code, 403)
        r=self.admin.post('/api/asistente/zonas/', {'nombre':'  Taller  ', 'ambiente':'operaciones'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['nombre'], 'Taller')
        self.assertEqual(self.admin.patch(f"/api/asistente/zonas/{r.data['id']}/", {'descripcion':'Telas y muebles'}, format='json').status_code, 200)
        r=self.admin.patch(f'/api/asistente/perfiles/{self.perfil.pk}/', {'zona':r.data['id']}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotEqual(r.data['zona'],self.zona.pk)
        visibles=self.lector.get('/api/asistente/perfiles/').data
        self.assertEqual(next(p for p in visibles if p['id']==self.perfil.pk)['zona'],r.data['zona'])

    def test_valida_zona_ambiente_nombre_y_limite(self):
        for datos in [{'nombre':' '}, {'nombre':'Taller','ambiente':'otro'}]:
            self.assertEqual(self.admin.post('/api/asistente/zonas/',datos,format='json').status_code,400)
        self.assertEqual(self.admin.patch(f'/api/asistente/perfiles/{self.perfil.pk}/',{'zona':999999},format='json').status_code,400)
        while ZonaOficinaIA.objects.count()<12:
            ZonaOficinaIA.objects.create(nombre='Zona de prueba')
        self.assertEqual(self.admin.post('/api/asistente/zonas/',{'nombre':'Sobra'},format='json').status_code,400)
        self.assertEqual(ZonaOficinaIA.objects.count(),12)

    def test_historial_general_perfil_y_actividad_son_personales(self):
        general=ConversacionAsistente.objects.create(usuario=self.gerente,titulo='General')
        propia=ConversacionAsistente.objects.create(usuario=self.gerente,titulo='Perfil',perfil=self.perfil)
        ajena=ConversacionAsistente.objects.create(usuario=self.vendedor,titulo='Ajena',perfil=self.perfil)
        vieja=ConversacionAsistente.objects.create(usuario=self.gerente,titulo='Interrumpida',perfil=self.perfil)
        MensajeAsistente.objects.create(conversacion=propia,rol='asistente',texto='',estado='procesando')
        m=MensajeAsistente.objects.create(conversacion=vieja,rol='asistente',texto='',estado='procesando')
        MensajeAsistente.objects.filter(pk=m.pk).update(creado=timezone.now()-timedelta(minutes=6))
        datos=self.admin.get('/api/asistente/conversaciones/').data
        self.assertEqual({c['id'] for c in datos},{general.pk,propia.pk,vieja.pk})
        self.assertTrue(next(c['activa'] for c in datos if c['id']==propia.pk))
        self.assertTrue(next(c['perfil']['activo'] for c in datos if c['id']==propia.pk))
        self.assertFalse(next(c['activa'] for c in datos if c['id']==vieja.pk))
        self.assertEqual({c['id'] for c in self.admin.get('/api/asistente/conversaciones/',{'perfil':self.perfil.pk}).data},{propia.pk,vieja.pk})
        self.assertEqual([c['id'] for c in self.admin.get('/api/asistente/conversaciones/',{'perfil':'general'}).data],[general.pk])
        self.assertEqual(self.admin.get(f'/api/asistente/conversaciones/{ajena.pk}/').status_code,404)
        self.assertEqual(self.admin.get('/api/asistente/conversaciones/',{'perfil':'mal'}).status_code,400)

    def test_no_trunca_historial_y_prioriza_trabajo_activo(self):
        activa=ConversacionAsistente.objects.create(usuario=self.gerente,titulo='Activa antigua',perfil=self.perfil)
        MensajeAsistente.objects.create(conversacion=activa,rol='asistente',texto='',estado='procesando')
        ConversacionAsistente.objects.bulk_create([ConversacionAsistente(usuario=self.gerente,titulo=f'Anterior {i}') for i in range(105)])
        primera=self.admin.get('/api/asistente/conversaciones/').data
        segunda=self.admin.get('/api/asistente/conversaciones/',{'offset':100}).data
        self.assertEqual(primera[0]['id'],activa.pk)
        self.assertEqual(len(primera),100)
        self.assertEqual(len(segunda),6)
        self.assertEqual(len({c['id'] for c in primera+segunda}),106)
        self.assertEqual(self.admin.get('/api/asistente/conversaciones/',{'offset':-1}).status_code,400)

    def test_entrenamiento_se_puede_configurar_como_ambiente(self):
        r=self.admin.patch(f'/api/asistente/zonas/{self.zona.pk}/',{'ambiente':'entrenamiento'},format='json')
        self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(r.data['ambiente'],'entrenamiento')
        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.zona_id,self.zona.pk)

    def test_migracion_entrenamiento_conserva_perfiles_historial_y_personalizaciones(self):
        ZonaOficinaIA.objects.filter(nombre='Entrenamiento').delete()
        self.zona.nombre='Tecnología'
        self.zona.ambiente='tecnologia'
        self.zona.descripcion='Herramientas, infraestructura e inteligencia artificial'
        self.zona.save()
        otra=ZonaOficinaIA.objects.create(nombre='Mi laboratorio',ambiente='tecnologia',descripcion='Mi descripción')
        conv=ConversacionAsistente.objects.create(usuario=self.gerente,perfil=self.perfil,titulo='Historial existente')
        migracion=import_module('ordenes.migrations.0064_entrenamiento_oficina_ia')
        for _ in range(2):
            migracion.convertir_entrenamiento(apps,SimpleNamespace(connection=connection))
        self.zona.refresh_from_db();self.perfil.refresh_from_db();conv.refresh_from_db();otra.refresh_from_db()
        self.assertEqual(self.zona.nombre,'Entrenamiento')
        self.assertEqual(self.zona.ambiente,'entrenamiento')
        self.assertEqual(self.perfil.zona_id,self.zona.pk)
        self.assertEqual(conv.perfil_id,self.perfil.pk)
        self.assertEqual((otra.nombre,otra.descripcion,otra.ambiente),('Mi laboratorio','Mi descripción','entrenamiento'))
