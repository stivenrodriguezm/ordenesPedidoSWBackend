import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lottusPedidos.settings')
django.setup()

from django.apps import apps
from django.db import connection, transaction
from django.contrib.auth import get_user_model
from ordenes.models import RolePermission

User = get_user_model()

def seed_default_roles():
    print("Seeding default RolePermission records...")
    default_roles = [
        {
            'role': 'administrador',
            'permissions': [
                'ALL', 'VER_INICIO', 'VER_VENTAS', 'CREAR_VENTA', 'EDITAR_VENTA', 
                'VER_ORDENES', 'CREAR_ORDEN', 'VER_TELAS', 'VER_REFERENCIAS', 
                'VER_PROVEEDORES', 'VER_CLIENTES', 'VER_FACTURAS', 'VER_REMISIONES', 
                'VER_INVENTARIO', 'VER_CAJA', 'GESTION_USUARIOS'
            ]
        },
        {
            'role': 'vendedor',
            'permissions': [
                'VER_INICIO', 'VER_VENTAS', 'CREAR_VENTA', 'VER_ORDENES', 
                'CREAR_ORDEN', 'VER_TELAS', 'VER_REFERENCIAS', 'VER_CLIENTES'
            ]
        },
        {
            'role': 'auxiliar',
            'permissions': [
                'VER_INICIO', 'VER_VENTAS', 'VER_ORDENES', 'VER_TELAS', 
                'VER_REFERENCIAS', 'VER_PROVEEDORES', 'VER_CLIENTES', 
                'VER_FACTURAS', 'VER_REMISIONES', 'VER_INVENTARIO', 'VER_CAJA'
            ]
        },
        {
            'role': 'transportador',
            'permissions': [
                'VER_INICIO', 'VER_REMISIONES'
            ]
        }
    ]
    
    for rdata in default_roles:
        rp, created = RolePermission.objects.get_or_create(role=rdata['role'])
        rp.permissions = rdata['permissions']
        rp.save()
        status = "Created" if created else "Updated"
        print(f"  - {status} role '{rdata['role']}' with permissions: {rdata['permissions']}")

def clear_database():
    print("Starting database cleanup...")
    
    # Identify database engine
    engine = connection.settings_dict.get('ENGINE', '')
    is_mysql = 'mysql' in engine
    is_sqlite = 'sqlite' in engine

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Disable foreign key checks
            if is_mysql:
                print("Disabling foreign key checks (MySQL)...")
                cursor.execute('SET FOREIGN_KEY_CHECKS = 0;')
            elif is_sqlite:
                print("Disabling foreign key checks (SQLite)...")
                cursor.execute('PRAGMA foreign_keys = OFF;')

            # Iterate over all models and delete records
            all_models = apps.get_models()
            for model in all_models:
                # Skip django admin log, content types, permissions, sessions, group models to keep django structure clean
                model_name = model.__name__
                app_label = model._meta.app_label
                if app_label in ('admin', 'contenttypes', 'auth', 'sessions'):
                    # But we DO want to filter the User model itself (which is typically auth.User, but here it is CustomUser in ordenes)
                    if model != User:
                        continue

                if model == User:
                    print("Filtering and deleting non-admin users...")
                    users_to_delete = User.objects.exclude(role='administrador').exclude(is_superuser=True)
                    count = users_to_delete.count()
                    users_to_delete.delete()
                    print(f"Deleted {count} non-admin users.")
                else:
                    print(f"Deleting all records from model {app_label}.{model_name}...")
                    try:
                        count = model.objects.all().count()
                        model.objects.all().delete()
                        if count > 0:
                            print(f"  Deleted {count} records.")
                    except Exception as e:
                        print(f"  Error deleting records from {model_name}: {e}")

            # Seed default roles
            seed_default_roles()

            # Re-enable foreign key checks
            if is_mysql:
                print("Enabling foreign key checks (MySQL)...")
                cursor.execute('SET FOREIGN_KEY_CHECKS = 1;')
            elif is_sqlite:
                print("Enabling foreign key checks (SQLite)...")
                cursor.execute('PRAGMA foreign_keys = ON;')

    print("\nRemaining users in database:")
    for u in User.objects.all():
        print(f"- {u.username} (Role: {u.role}, Superuser: {u.is_superuser})")

    print("\nDatabase cleanup completed successfully!")

if __name__ == "__main__":
    clear_database()
