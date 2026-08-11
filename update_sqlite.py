import sqlite3
import json

db_paths = ['db.sqlite3', 'db_local.sqlite3']

for db_path in db_paths:
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paginaweb_setting'")
        if not cursor.fetchone():
            print(f"Table paginaweb_setting not found in {db_path}")
            continue

        value = "Cada pieza nace en nuestro estudio creativo y toma forma en manos de maestros artesanos bogotanos. Para quienes entienden que un hogar no se decora: se compone."
        value_json = json.dumps(value)
        
        cursor.execute("UPDATE paginaweb_setting SET value = ? WHERE key = 'heroSubtitle'", (value_json,))
        conn.commit()
        print(f"Updated heroSubtitle in {db_path}")
        conn.close()
    except Exception as e:
        print(f"Error updating {db_path}: {e}")
