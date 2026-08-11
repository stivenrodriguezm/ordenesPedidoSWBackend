import pymysql
import json

try:
    conn = pymysql.connect(
        host='195.35.61.108',
        user='u756180748_root',
        password='Lottus123',
        database='u756180748_pruebasv3',
        port=3306
    )
    with conn.cursor() as cursor:
        value = "Cada pieza nace en nuestro estudio creativo y toma forma en manos de maestros artesanos bogotanos. Para quienes entienden que un hogar no se decora: se compone."
        value_json = json.dumps(value)
        cursor.execute("UPDATE paginaweb_setting SET value = %s WHERE `key` = 'heroSubtitle'", (value_json,))
        conn.commit()
        print("Update in backend successful")
        
        # Now let's try updating the other database just in case the frontend is using it directly sometimes
        try:
            conn2 = pymysql.connect(
                host='195.35.61.108',
                user='u756180748_tienda',
                password='Lottus333',
                database='u756180748_tienda',
                port=3306
            )
            with conn2.cursor() as cursor2:
                cursor2.execute("UPDATE settings SET value = %s WHERE `key` = 'heroSubtitle'", (value_json,))
                conn2.commit()
                print("Update in frontend DB successful")
        except Exception as e2:
            print(f"Error connecting to frontend DB: {e2}")

except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals() and conn:
        conn.close()
