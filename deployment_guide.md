# Guía de Despliegue en Producción - Hostinger VPS & MySQL (`api.muebleslottus.com`)

Esta guía describe el procedimiento oficial para ejecutar las migraciones y desplegar el backend en el servidor **Hostinger VPS** usando la base de datos MySQL en Hostinger (`u756180748_lottus`).

---

## 1. Respaldo de Seguridad de la Base de Datos Real (phpMyAdmin / SSH)

Antes de hacer las migraciones, realiza una copia de seguridad de la base de datos de producción `u756180748_lottus`:

### Opción A (Desde el panel phpMyAdmin de Hostinger):
1. Entra al panel de **Hostinger -> Bases de Datos MySQL -> phpMyAdmin**.
2. Selecciona la base de datos `u756180748_lottus`.
3. Haz clic en la pestaña **Exportar**.
4. Selecciona el formato **SQL** y haz clic en **Exportar** para descargar la copia en tu equipo.

### Opción B (Desde la terminal del VPS Hostinger):
```bash
mysqldump -h 195.35.61.108 -u u756180748_lottus -p'Lottus123' u756180748_lottus > backup_lottus_real_$(date +%F_%H%M%S).sql
```

---

## 2. Instalación de Paquetes en Hostinger VPS (Sin Entorno Virtual)

En tu VPS de Hostinger, instala las dependencias directamente en Python global de la máquina:

```bash
# Actualizar el sistema e instalar dependencias
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip git nginx certbot python3-certbot-nginx libmysqlclient-dev

# Instalar los paquetes del proyecto directamente
cd /var/www/backend  # O la ruta donde tengas clonado el repositorio en Hostinger VPS
pip3 install -r requirements.txt
```

---

## 3. Ejecución Directa de Migraciones en Producción

Con los accesos de la base de datos `u756180748_lottus` configurados en `settings.py` o `.env`:

```bash
cd /var/www/backend

# 1. Comprobar las migraciones registradas
python3 manage.py showmigrations

# 2. Generar posibles migraciones de modelos
python3 manage.py makemigrations

# 3. Aplicar las migraciones a la base de datos real en Hostinger
python3 manage.py migrate

# 4. Recolectar archivos estáticos
python3 manage.py collectstatic --noinput
```

---

## 4. Configurar Gunicorn en Systemd (Directo con Python3)

Crea el archivo de servicio para Gunicorn:

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

Pega la siguiente configuración:

```ini
[Unit]
Description=Gunicorn daemon for Lottus Backend API (Hostinger VPS)
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/backend
ExecStart=/usr/local/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 lottusPedidos.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

*Nota: Si `gunicorn` fue instalado en `/usr/bin/gunicorn`, ajusta el `ExecStart` ejecutando previamente `which gunicorn`.*

Reinicia el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl enable gunicorn
```

---

## 5. Nginx & Certificado SSL (HTTPS)

Asegúrate de que Nginx redirija las peticiones a `api.muebleslottus.com` y activa el certificado SSL:

```bash
sudo certbot --nginx -d api.muebleslottus.com
```
