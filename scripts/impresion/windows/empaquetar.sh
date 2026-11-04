#!/bin/bash
# Arma LottusImpresion-Windows.zip: agente, instalador, Python portátil y SumatraPDF. No lleva
# config.json (tiene el token): ese se entrega aparte.
#   ./empaquetar.sh CARPETA_DE_SALIDA
set -euo pipefail
PY_VERSION=3.12.10
SUMATRA_VERSION=3.5.2
SALIDA="${1:?Indica la carpeta de salida}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PAQUETE="$TMP/LottusImpresion-Windows"
mkdir -p "$PAQUETE/python" "$TMP/sumatra" "$SALIDA"

curl -fsSL -o "$TMP/python.zip" "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"
curl -fsSL -o "$TMP/sumatra.zip" "https://www.sumatrapdfreader.org/dl/rel/$SUMATRA_VERSION/SumatraPDF-$SUMATRA_VERSION-64.zip"
unzip -q "$TMP/python.zip" -d "$PAQUETE/python"
unzip -q "$TMP/sumatra.zip" -d "$TMP/sumatra"
cp "$TMP"/sumatra/SumatraPDF-*.exe "$PAQUETE/SumatraPDF.exe"
cp "$AQUI/../agente.py" "$AQUI/instalar.ps1" "$AQUI/instalar.bat" "$PAQUETE/"
(cd "$TMP" && zip -qr "LottusImpresion-Windows.zip" "LottusImpresion-Windows")
mv "$TMP/LottusImpresion-Windows.zip" "$SALIDA/"
shasum -a 256 "$TMP/python.zip" "$TMP/sumatra.zip" | awk '{print $1}'
echo "Paquete: $SALIDA/LottusImpresion-Windows.zip ($(du -h "$SALIDA/LottusImpresion-Windows.zip" | cut -f1))"
