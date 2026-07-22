import os
import django
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lottusPedidos.settings")
django.setup()

from suministros.models import Inventario

for item in Inventario.objects.all():
    item.qr_uuid = uuid.uuid4()
    item.save()

print("UUIDs populated successfully.")
