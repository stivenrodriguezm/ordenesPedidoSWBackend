from suministros.models import Sede, Zona

sede1, _ = Sede.objects.get_or_create(nombre="Sede 1")
for z in ["Piso 1", "Piso 2", "Piso 3", "Apartamento", "Bodega 1", "Bodega 2"]:
    Zona.objects.get_or_create(sede=sede1, nombre=z)

sede2, _ = Sede.objects.get_or_create(nombre="Sede 2")
for z in ["Sótano", "Piso 1", "Piso 2"]:
    Zona.objects.get_or_create(sede=sede2, nombre=z)

print("Zonas creadas exitosamente.")
