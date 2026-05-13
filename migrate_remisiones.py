
from suministros.models import RemisionSuministro
from ordenes.models import CustomUser

# Map existing transportador names to user instances
# We look for user's first_name or username matching the string
transportadores = CustomUser.objects.filter(role='transportador')
name_to_user = {}
for u in transportadores:
    if u.first_name:
        name_to_user[u.first_name.strip().lower()] = u
    name_to_user[u.username.strip().lower()] = u

updated = 0
for rem in RemisionSuministro.objects.filter(transportador_usuario__isnull=True):
    name = (rem.transportador or "").strip().lower()
    if name in name_to_user:
        rem.transportador_usuario = name_to_user[name]
        rem.save()
        updated += 1

print(f"Successfully linked {updated} old remisiones to users.")
