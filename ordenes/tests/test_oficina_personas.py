from datetime import timedelta
from django.utils import timezone
from ordenes.models import (ConfiguracionOficina, MiembroOficina, MensajeOficina, TrabajoOficina,
                           ComentarioTrabajoOficina, ZonaOficinaIA)
from ordenes.tests.utils import LottusTestCase


class OficinaPersonasTests(LottusTestCase):
    def setUp(self):
        self.dueno=self.crear_usuario('dueno_oficina','administrador')
        self.otroadmin=self.crear_usuario('otro_admin','administrador')
        self.ana=self.crear_usuario('persona_ana')
        self.luis=self.crear_usuario('persona_luis')
        self.ajeno=self.crear_usuario('no_invitado')
        self.permisos('vendedor',['VER_PROPIAS_VENTAS'])
        self.c=ConfiguracionOficina.objects.create(responsable=self.dueno)
        for u in [self.dueno,self.ana,self.luis]:MiembroOficina.objects.create(usuario=u)
        self.admin=self.api(self.dueno);self.a=self.api(self.ana);self.l=self.api(self.luis)

    def test_invitacion_no_da_acceso_ia_ni_ventas_ajenas(self):
        r=self.a.get('/api/oficina/estado/');self.assertEqual(r.status_code,200)
        self.assertFalse(r.data['puede_usar_ia'])
        self.assertTrue(self.a.get('/api/user/').data['acceso_oficina'])
        self.assertEqual(self.a.post('/api/asistente/preguntar/',{'texto':'hola'},format='json').status_code,403)
        self.assertEqual(self.api(self.ajeno).get('/api/oficina/estado/').status_code,403)
        propia=self.venta(self.ana);ajena=self.venta(self.luis)
        r=self.a.get(f'/api/oficina/personas/{self.ana.pk}/ventas/')
        self.assertEqual([v['id'] for v in r.data['ventas']],[propia.pk])
        self.assertNotIn(ajena.pk,[v['id'] for v in r.data['ventas']])
        self.assertEqual(self.a.get(f'/api/oficina/personas/{self.luis.pk}/ventas/').status_code,403)

    def test_equipo_solo_responsable_revision_puestos_y_retiro_sin_borrar(self):
        self.assertEqual(self.api(self.otroadmin).get('/api/oficina/equipo/').status_code,403)
        self.assertEqual(self.a.put('/api/oficina/equipo/',{},format='json').status_code,403)
        m=MensajeOficina.objects.create(autor=self.ana,texto='Aviso existente')
        comercial=ZonaOficinaIA.objects.filter(ambiente='showroom').first()
        r=self.admin.put('/api/oficina/equipo/',{'revision':1,'personas':[{'usuario':self.ana.pk,'zona':comercial.pk,'puesto':0},{'usuario':self.luis.pk,'zona':comercial.pk,'puesto':0}]},format='json')
        self.assertEqual(r.status_code,400)
        r=self.admin.put('/api/oficina/equipo/',{'revision':1,'personas':[{'usuario':self.luis.pk,'zona':comercial.pk,'puesto':1}]},format='json')
        self.assertEqual(r.status_code,200,r.data)
        self.assertTrue(MensajeOficina.objects.filter(pk=m.pk).exists())
        self.assertEqual(self.a.post('/api/oficina/mensajes/',{'texto':'Bloqueado'},format='json').status_code,403)
        self.assertEqual(self.admin.put('/api/oficina/equipo/',{'revision':1,'personas':[]},format='json').status_code,409)
        self.assertTrue(MiembroOficina.objects.get(usuario=self.luis).habilitado)

    def test_usuario_inactivo_no_es_candidato_y_se_rechaza(self):
        self.luis.is_active=False;self.luis.save()
        ids=[p['id'] for p in self.admin.get('/api/oficina/equipo/').data['personas']]
        self.assertNotIn(self.luis.pk,ids)
        self.assertEqual(self.admin.put('/api/oficina/equipo/',{'revision':1,'personas':[{'usuario':self.luis.pk}]},format='json').status_code,400)

    def test_mensajes_privados_no_visibles_para_tercero_ni_responsable(self):
        r=self.a.post('/api/oficina/mensajes/',{'texto':'Privado','destinatario':self.luis.pk},format='json');self.assertEqual(r.status_code,201)
        pk=r.data['id']
        self.assertEqual(len(self.l.get('/api/oficina/mensajes/',{'para':self.ana.pk}).data['resultados']),1)
        self.assertEqual(self.admin.get('/api/oficina/mensajes/',{'para':self.ana.pk}).data['resultados'],[])
        self.assertEqual(self.admin.patch(f'/api/oficina/mensajes/{pk}/',{'archivado':True},format='json').status_code,403)
        self.assertEqual(self.admin.post('/api/oficina/mensajes/leer/',{'ids':[pk]},format='json').data['marcados'],0)
        self.assertEqual(self.l.post('/api/oficina/mensajes/leer/',{'ids':[pk]},format='json').data['marcados'],1)
        self.assertEqual(self.l.get('/api/oficina/estado/').data['mensajes_sin_leer'],0)

    def test_destacado_solo_publico_uno_por_autor_y_caduca(self):
        self.assertEqual(self.a.post('/api/oficina/mensajes/',{'texto':'Privado','destinatario':self.luis.pk,'destacar':True},format='json').status_code,400)
        anterior=self.a.post('/api/oficina/mensajes/',{'texto':'Primero','destacar':True,'horas':1},format='json').data
        actual=self.a.post('/api/oficina/mensajes/',{'texto':'Segundo','destacar':True,'horas':4},format='json').data
        self.assertIsNone(MensajeOficina.objects.get(pk=anterior['id']).destacado_hasta)
        p=next(p for p in self.admin.get('/api/oficina/estado/').data['personas'] if p['id']==self.ana.pk)
        self.assertEqual(p['destacado']['texto'],'Segundo')
        MensajeOficina.objects.filter(pk=actual['id']).update(destacado_hasta=timezone.now()-timedelta(seconds=1))
        p=next(p for p in self.admin.get('/api/oficina/estado/').data['personas'] if p['id']==self.ana.pk)
        self.assertIsNone(p['destacado'])

    def test_solicitud_se_dirige_al_dueno_y_solo_el_la_resuelve(self):
        r=self.a.post('/api/oficina/trabajos/',{'tipo':'solicitud','titulo':'Actualizar ficha','responsable':self.luis.pk},format='json')
        self.assertEqual(r.status_code,201,r.data);pk=r.data['id']
        self.assertEqual(r.data['responsable']['id'],self.dueno.pk)
        self.assertEqual(self.l.get(f'/api/oficina/trabajos/{pk}/').status_code,404)
        self.assertEqual(self.a.patch(f'/api/oficina/trabajos/{pk}/',{'revision':1,'estado':'hecha'},format='json').status_code,403)
        r=self.admin.patch(f'/api/oficina/trabajos/{pk}/',{'revision':1,'estado':'en_curso'},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.admin.patch(f'/api/oficina/trabajos/{pk}/',{'revision':1,'estado':'hecha'},format='json').status_code,409)
        self.assertEqual(self.a.post(f'/api/oficina/trabajos/{pk}/comentarios/',{'texto':'Gracias'},format='json').status_code,201)
        self.assertEqual(ComentarioTrabajoOficina.objects.filter(trabajo_id=pk).count(),2)
        self.assertEqual(self.l.post(f'/api/oficina/trabajos/{pk}/comentarios/',{'texto':'Ajeno'},format='json').status_code,404)

    def test_tareas_asignadas_propias_y_venta_solo_si_ambos_tienen_acceso(self):
        datos={'tipo':'tarea','titulo':'Seguir pedido','responsable':self.luis.pk}
        self.assertEqual(self.a.post('/api/oficina/trabajos/',datos,format='json').status_code,403)
        venta=self.venta(self.ana)
        self.assertEqual(self.admin.post('/api/oficina/trabajos/',{**datos,'venta':venta.pk},format='json').status_code,400)
        r=self.admin.post('/api/oficina/trabajos/',{**datos,'responsable':self.ana.pk,'venta':venta.pk},format='json')
        self.assertEqual(r.status_code,201,r.data)
        self.assertEqual(self.a.get(f"/api/oficina/trabajos/{r.data['id']}/").data['venta'],venta.pk)
        self.assertEqual(self.l.get(f"/api/oficina/trabajos/{r.data['id']}/").status_code,404)
        self.assertEqual(self.a.post('/api/oficina/trabajos/',{'tipo':'tarea','titulo':'Propia'},format='json').status_code,201)

    def test_presencia_y_estado_pertenecen_a_usuario_actual_y_expiran(self):
        r=self.a.post('/api/oficina/presencia/',{'estado':'ocupado','nota_estado':'Con un cliente'},format='json');self.assertEqual(r.status_code,200)
        p=next(p for p in self.admin.get('/api/oficina/estado/').data['personas'] if p['id']==self.ana.pk)
        self.assertTrue(p['en_oficina']);self.assertEqual(p['estado'],'ocupado')
        self.assertEqual(self.a.post('/api/oficina/presencia/',{'usuario':self.luis.pk},format='json').status_code,400)
        MiembroOficina.objects.filter(usuario=self.ana).update(ultima_presencia=timezone.now()-timedelta(minutes=3))
        p=next(p for p in self.admin.get('/api/oficina/estado/').data['personas'] if p['id']==self.ana.pk)
        self.assertFalse(p['en_oficina'])

    def test_get_no_configura_oficina_y_primer_guardado_fija_responsable(self):
        self.c.delete()
        self.admin.get('/api/oficina/estado/');self.admin.get('/api/oficina/equipo/')
        self.assertFalse(ConfiguracionOficina.objects.exists())
        r=self.admin.put('/api/oficina/equipo/',{'revision':0,'personas':[{'usuario':self.ana.pk}]},format='json')
        self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(ConfiguracionOficina.objects.get().responsable_id,self.dueno.pk)
        self.assertEqual(self.api(self.otroadmin).put('/api/oficina/equipo/',{'revision':1,'personas':[]},format='json').status_code,403)

    def test_contenido_se_valida_y_la_paginacion_no_revela_otros_chats(self):
        self.assertEqual(self.a.post('/api/oficina/mensajes/',{'texto':' '*4},format='json').status_code,400)
        self.assertEqual(self.a.post('/api/oficina/mensajes/',{'texto':'Hola','autor':self.luis.pk},format='json').status_code,400)
        self.assertEqual(self.a.get('/api/oficina/mensajes/',{'offset':-1}).status_code,400)
        self.assertEqual(self.a.patch('/api/oficina/trabajos/1/',{'revision':1,'creador':self.luis.pk},format='json').status_code,400)


class BandejaChatsTests(LottusTestCase):
    """Bandeja de chats y aviso de mensajes en la oficina (2026-10-09)."""

    def setUp(self):
        self.dueno=self.crear_usuario('dueno_bandeja','administrador',first_name='Dueño')
        self.ana=self.crear_usuario('ana_bandeja',first_name='Ana')
        self.luis=self.crear_usuario('luis_bandeja',first_name='Luis')
        ConfiguracionOficina.objects.create(responsable=self.dueno)
        for u in [self.dueno,self.ana,self.luis]:MiembroOficina.objects.create(usuario=u)
        self.a,self.l=self.api(self.ana),self.api(self.luis)

    def test_lista_cada_chat_con_ultimo_mensaje_y_no_leidos(self):
        self.a.post('/api/oficina/mensajes/',{'texto':'Hola Luis','destinatario':self.luis.pk},format='json')
        self.l.post('/api/oficina/mensajes/',{'texto':'Hola equipo'},format='json')
        self.a.post('/api/oficina/mensajes/',{'texto':'¿Me ayudas con la venta?','destinatario':self.luis.pk},format='json')
        MensajeOficina.objects.create(autor=self.dueno,destinatario=self.ana,texto='Privado de otros')
        chats=self.l.get('/api/oficina/conversaciones/').data['resultados']
        self.assertEqual([c['para'] for c in chats],[str(self.ana.pk),'equipo'])
        self.assertEqual(chats[0]['ultimo']['texto'],'¿Me ayudas con la venta?')
        self.assertEqual(chats[0]['sin_leer'],2)
        self.assertEqual(chats[0]['persona']['nombre'],'Ana')
        estado=self.l.get('/api/oficina/estado/').data
        ana=next(p for p in estado['personas'] if p['id']==self.ana.pk)
        self.assertEqual((ana['mensajes_para_mi'],estado['mensajes_sin_leer']),(2,2))
        self.assertEqual(estado['mensajes_de'],[{'id':self.ana.pk,'cantidad':2}])
        # Quien envió no ve avisos de sus propios mensajes.
        self.assertEqual(self.a.get('/api/oficina/estado/').data['mensajes_sin_leer'],1)
        self.assertEqual([c['para'] for c in self.a.get('/api/oficina/conversaciones/').data['resultados']],
                         [str(self.dueno.pk),str(self.luis.pk),'equipo'])  # el más reciente primero

    def test_requiere_ser_del_equipo(self):
        ajeno=self.crear_usuario('ajeno_bandeja')
        self.assertEqual(self.api(ajeno).get('/api/oficina/conversaciones/').status_code,403)
