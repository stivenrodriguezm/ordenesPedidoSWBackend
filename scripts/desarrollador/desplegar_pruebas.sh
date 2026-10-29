#!/bin/bash
# Despliega una rama en la versión de PRUEBAS (backend :8443, base u756180748_pruebasv3).
# Lo ejecuta el servicio Desarrollador como el usuario stiven (regla de sudo con este script fijo):
#     sudo -n -u stiven /opt/lottus-desarrollador/desplegar_pruebas.sh <main|desarrollador/tN>
# Respalda pruebasv3 antes de migrar, migra con destinos explícitos (nunca ordenes 0057/0061 de
# Bancos) y reinicia gunicorn-pruebas. Nunca toca producción.
set -euo pipefail
REF="${1:?Indica la rama}"
[[ "$REF" =~ ^(main|desarrollador/t[0-9]+)$ ]] || { echo "Rama no permitida: $REF"; exit 2; }
DIR=/home/stiven/lottus-pruebas
RESPALDOS=/home/stiven/respaldos_pruebas
cd "$DIR"

git fetch -q origin "$REF"
git reset -q --hard FETCH_HEAD
echo "código: $(git log --oneline -1 | cut -c1-70)"
venv/bin/pip install -q -r requirements.txt

venv/bin/python manage.py shell -c "
from django.db import connection
c = connection.cursor(); c.execute('SELECT DATABASE()'); n = c.fetchone()[0]
assert n == 'u756180748_pruebasv3', 'La base no es la de pruebas'
" 2>/dev/null

PENDIENTES=$(venv/bin/python manage.py showmigrations --plan 2>/dev/null | grep -F "[ ]" | grep -v -E "ordenes\.(0057|0061)_" || true)
if [ -n "$PENDIENTES" ]; then
  umask 077
  mkdir -p "$RESPALDOS"
  CNF=$(mktemp)
  trap 'rm -f "$CNF"' EXIT
  venv/bin/python - "$CNF" <<'PY'
import os, sys
from dotenv import dotenv_values
e = dotenv_values('.env')
assert e['DB_NAME'] == 'u756180748_pruebasv3'
q = lambda v: '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
open(sys.argv[1], 'w').write(f"[client]\nhost={e['DB_HOST']}\nport={e.get('DB_PORT') or 3306}\nuser={q(e['DB_USER'])}\npassword={q(e['DB_PASSWORD'])}\n")
PY
  F="$RESPALDOS/pruebasv3_$(date +%Y%m%d_%H%M%S).sql.gz"
  EXTRA=""
  mysqldump --help 2>/dev/null | grep -q column-statistics && EXTRA="--column-statistics=0"
  mysqldump --defaults-extra-file="$CNF" --single-transaction --quick --no-tablespaces $EXTRA u756180748_pruebasv3 | gzip > "$F"
  gzip -t "$F" && zcat "$F" | tail -1 | grep -q "Dump completed" || { echo "El respaldo de pruebasv3 quedó incompleto; no se migra"; exit 3; }
  rm -f "$CNF"
  ls -1t "$RESPALDOS"/pruebasv3_*.sql.gz | tail -n +16 | xargs -r rm -f
  echo "respaldo pruebasv3: $(basename "$F")"
  venv/bin/python manage.py shell < /opt/lottus-desarrollador/migrar_pruebas.py
fi

venv/bin/python manage.py collectstatic --noinput -v 0
venv/bin/python manage.py shell -c "from django.core.cache import cache; cache.clear()" 2>/dev/null
sudo -n /usr/bin/systemctl restart gunicorn-pruebas
sleep 3
CODIGO=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: api.muebleslottus.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8001/api/health/)
[ "$CODIGO" = "200" ] || { echo "El backend de pruebas no respondió (HTTP $CODIGO)"; exit 4; }
echo "pruebas en línea con $REF"
