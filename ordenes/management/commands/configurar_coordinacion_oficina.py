"""Activación explícita sobre personas/perfiles existentes; no crea identidades."""
from datetime import time
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from ordenes.models import CoordinacionOficina, CustomUser, PerfilAsistente, ConfiguracionOficina
from ordenes.coordinacion import siguiente
from ordenes.servicios import auditar


class Command(BaseCommand):
    help = 'Configura el informe compartido de gerencia con IDs reales ya invitados.'

    def add_arguments(self,parser):
        parser.add_argument('--destinatarios',type=int,nargs='+',required=True)
        parser.add_argument('--coach',type=int,required=True)
        parser.add_argument('--analista',type=int,required=True)
        parser.add_argument('--activar',action='store_true')
        parser.add_argument('--hora-fin',default='18:50')

    def handle(self,*args,**opciones):
        try:cierre=time.fromisoformat(opciones['hora_fin'])
        except ValueError:raise CommandError('Hora de cierre inválida.')
        if cierre<time(9,50) or cierre.minute!=50 or cierre.second:raise CommandError('El cierre debe ser a :50, desde las 09:50.')
        ids=set(opciones['destinatarios'])
        with transaction.atomic():
            oficina=ConfiguracionOficina.objects.select_for_update().filter(pk=1).first()
            usuarios=list(CustomUser.objects.filter(pk__in=ids,is_active=True,role='administrador',membresia_oficina__habilitado=True))
            if len(usuarios)!=len(ids) or not oficina or oficina.responsable_id not in ids:
                raise CommandError('Se requieren gerentes activos invitados y el responsable de la oficina.')
            coach=PerfilAsistente.objects.filter(pk=opciones['coach'],activo=True,zona__ambiente='entrenamiento').first()
            analista=PerfilAsistente.objects.filter(pk=opciones['analista'],activo=True,zona__ambiente='showroom').first()
            if not coach or not analista:raise CommandError('Coach y analista deben existir y estar ubicados en sus áreas.')
            config,creada=CoordinacionOficina.objects.get_or_create(pk=1)
            if not creada:raise CommandError('Ya hay una programación. Modifícala desde la oficina para preservar sus decisiones.')
            config.destinatarios.set(usuarios)
            config.lideres={str(coach.zona_id):coach.pk,str(analista.zona_id):analista.pk}
            config.hora_inicio=time(9,50);config.hora_fin=cierre;config.dias=list(range(7));config.activa=opciones['activar']
            config.proxima_ejecucion=siguiente(config);config.save()
            auditar(oficina.responsable,'oficina.coordinacion.crear',config,{'destinatarios':sorted(ids),'activa':config.activa})
        self.stdout.write('Programa creado: 09:50–'+cierre.strftime('%H:%M')+' Bogotá, cada hora, todos los días. Cierre y días editables en /IA.')
