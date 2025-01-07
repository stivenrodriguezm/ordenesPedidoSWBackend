from django.db.models.signals import post_save
from django.contrib.auth.models import User
from .models import PerfilUsuario

def crear_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        PerfilUsuario.objects.create(usuario=instance)

post_save.connect(crear_perfil_usuario, sender=User)
