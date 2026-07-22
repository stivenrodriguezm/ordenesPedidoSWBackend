import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lottusPedidos.settings')
django.setup()

from suministros.models import Inventario

def run():
    count = Inventario.objects.filter(estado_fisico='nuevo').update(estado_fisico='buen_estado')
    print(f"Éxito: Se han actualizado {count} registros que tenían el estado 'nuevo' a 'buen_estado'.")

if __name__ == '__main__':
    run()
