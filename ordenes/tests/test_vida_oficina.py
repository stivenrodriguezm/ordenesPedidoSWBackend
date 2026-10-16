from datetime import time, timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from ordenes import vida_oficina as vida
from ordenes.asistente import automatizaciones, gemini
from ordenes.models import (AutomatizacionAsistente, ConversacionAsistente, ConfiguracionOficina,
    InteraccionOficina, MiembroOficina, MensajeAsistente, PerfilAsistente, ZonaOficinaIA)
from ordenes.tests.utils import LottusTestCase


@override_settings(GEMINI_API_KEY='ficticia',GEMINI_MODELOS=['modelo-a'],ASISTENTE_EN_SEGUNDO_PLANO=False)
class VidaOficinaTests(LottusTestCase):
    def setUp(self):
        self.admin=self.crear_usuario('gerente_vida','administrador')
        self.otro=self.crear_usuario('otro_vida','administrador')
        self.vendedor=self.crear_usuario('vendedor_vida')
        self.permisos('vendedor',['USAR_ASISTENTE_IA'])
        ConfiguracionOficina.objects.create(responsable=self.admin)
        self.zona=ZonaOficinaIA.objects.filter(ambiente='showroom').first()
        for u in [self.admin,self.otro,self.vendedor]:
            MiembroOficina.objects.create(usuario=u,zona=self.zona,ultima_presencia=timezone.now())
        self.p=PerfilAsistente.objects.create(nombre='Analista independiente',rol='Mejorar ventas',
            instrucciones='Tu objetivo es mejorar las ventas con evidencia real.',areas=['ventas'],zona=self.zona)

    def tarea(self):
        return AutomatizacionAsistente.objects.create(usuario=self.admin,perfil=self.p,perfil_nombre=self.p.nombre,
            nombre='Creada por el usuario',instrucciones='Analiza mis ventas y entrega recomendaciones.',
            frecuencia='diaria',hora=time(9),proxima_ejecucion=timezone.now()-timedelta(minutes=1))

    def test_todas_las_ejecuciones_emiten_trabajo_consulta_y_entrega_sin_duplicar(self):
        def responder(historial,usuario,avance,**kwargs):
            avance('resumen_ventas',{});avance('gestion_ventas',{})
            return {'texto':'Resultado de prueba','herramientas':[],'modelo':'modelo-a','tokens':1}
        for manual in [True,False]:
            a=self.tarea()
            e=automatizaciones.reservar(a.pk,self.admin.pk,'manual-vida' if manual else None) if manual else automatizaciones.reservar(a.pk)
            with patch.object(gemini,'responder',side_effect=responder):
                self.assertTrue(automatizaciones.ejecutar(e.pk))
                self.assertFalse(automatizaciones.ejecutar(e.pk))
            eventos=list(e.interacciones.all())
            self.assertEqual([x.tipo for x in eventos],['trabajo','analisis','entrega'])
            self.assertTrue(all(x.actor==f'ia-{self.p.pk}' for x in eventos))
            self.assertEqual(eventos[-1].destino,f'persona-{self.admin.pk}')
            self.assertTrue(all('Resultado de prueba' not in x.texto and a.nombre not in x.texto for x in eventos))

    def test_error_se_visita_para_revision_sin_entregar_exito(self):
        a=self.tarea();e=automatizaciones.reservar(a.pk)
        with patch.object(gemini,'responder',side_effect=gemini.ErrorAsistente('Prueba sin red')):
            automatizaciones.ejecutar(e.pk)
        self.assertEqual(list(e.interacciones.values_list('tipo',flat=True)),['trabajo','revision'])

    def test_iniciativas_privadas_acotadas_y_pendientes_no_se_repiten(self):
        with patch('ordenes.vida_oficina.PerfilAsistente.objects.filter',return_value=PerfilAsistente.objects.filter(pk=self.p.pk)):
            self.assertEqual(vida.impulsar(limite=10,forzar=True),2)
            self.assertEqual(vida.impulsar(limite=10,forzar=True),0)
        self.assertEqual(InteraccionOficina.objects.filter(tipo='dialogo').count(),2)
        self.assertFalse(ConversacionAsistente.objects.filter(usuario=self.vendedor).exists())
        datos=self.api(self.admin).get('/api/asistente/oficina-actividad/').data
        self.assertEqual(len(datos['iniciativas']),1)
        c=ConversacionAsistente.objects.get(pk=datos['iniciativas'][0]['conversacion'])
        self.assertEqual(c.usuario_id,self.admin.pk)
        self.assertEqual(self.api(self.otro).get(f'/api/asistente/conversaciones/{c.pk}/').status_code,404)
        InteraccionOficina.objects.filter(conversacion=c).update(creado=timezone.now()-timedelta(days=2))
        vida.abrir_dialogo(self.admin,self.p,'Una pregunta nueva que no debe duplicarse')
        self.assertEqual(ConversacionAsistente.objects.filter(usuario=self.admin).count(),1)
        MensajeAsistente.objects.create(conversacion=c,rol='usuario',texto='Prioriza el ticket promedio')
        vida.abrir_dialogo(self.admin,self.p,'¿Qué resultado quieres revisar ahora?')
        self.assertEqual(ConversacionAsistente.objects.filter(usuario=self.admin).count(),2)

    def test_colega_real_sin_recursion_y_sin_acceso_a_chats_ajenos(self):
        colega=PerfilAsistente.objects.create(nombre='Coach',rol='Formación',instrucciones='Usa evidencia.',areas=['ventas','formacion'])
        c=ConversacionAsistente.objects.create(usuario=self.admin,perfil=self.p)
        m=MensajeAsistente.objects.create(conversacion=c,rol='asistente',estado='procesando')
        with patch.object(gemini,'analizar_evidencia',return_value={'texto':'Pide evidencia del embudo','modelo':'modelo-a'}) as consulta:
            r=vida.colaborar('consultar_agente_oficina',{'agente_id':colega.pk,'pregunta':'¿Cómo comparar opciones de formación comercial?'},self.admin,self.p,m.pk,'modelo-a',25)
            self.assertEqual(r['criterio'],'Pide evidencia del embudo');self.assertEqual(consulta.call_count,1)
            self.assertIn('error',vida.colaborar('consultar_agente_oficina',{'agente_id':colega.pk,'pregunta':'Una pregunta de otra persona'},self.otro,self.p,m.pk,'modelo-a',25))
        self.assertEqual(c.interacciones.get().destino,f'ia-{colega.pk}')

    def test_eventos_no_revelan_agentes_ocultos_y_conservan_cursor(self):
        self.p.visible_todos=False;self.p.roles_visibles=['auxiliar'];self.p.save()
        e=vida.registrar(self.p,f'persona-{self.admin.pk}','consulta','Consultando una posibilidad')
        datos=self.api(self.vendedor).get('/api/oficina/interacciones/').data
        self.assertNotIn(e.pk,[x['id'] for x in datos['eventos']]);self.assertEqual(datos['cursor'],e.pk)
