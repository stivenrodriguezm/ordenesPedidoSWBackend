# Instala o actualiza el agente de impresión en el Windows de la oficina: copia los archivos
# a %LOCALAPPDATA%\LottusImpresion, elige la impresora y lo deja arrancando al iniciar sesión.
# Necesita config.json junto a este archivo (lo genera `manage.py crear_impresora`).
$ErrorActionPreference = 'Stop'
$origen = $PSScriptRoot
$destino = Join-Path $env:LOCALAPPDATA 'LottusImpresion'
$configOrigen = Join-Path $origen 'config.json'
$configDestino = Join-Path $destino 'config.json'

if (-not (Test-Path $configOrigen) -and -not (Test-Path $configDestino)) {
    Write-Host 'Falta config.json: copialo a esta carpeta y vuelve a ejecutar.' -ForegroundColor Red
    exit 1
}

# 1. La impresora: la Ricoh si hay una sola; si no, se pregunta.
$impresoras = @(Get-Printer | Select-Object -ExpandProperty Name)
$ricoh = @($impresoras | Where-Object { $_ -match 'ricoh|3710' })
if ($ricoh.Count -eq 1) {
    $cola = $ricoh[0]
} else {
    if ($impresoras.Count -eq 0) { Write-Host 'Este Windows no tiene impresoras instaladas. Instala la Ricoh primero.' -ForegroundColor Red; exit 1 }
    Write-Host 'Impresoras de este Windows:'
    for ($i = 0; $i -lt $impresoras.Count; $i++) { Write-Host "  $($i + 1). $($impresoras[$i])" }
    $cola = $impresoras[[int](Read-Host 'Numero de la Ricoh') - 1]
}
Write-Host "Impresora elegida: $cola"

# 2. Detener el agente anterior y copiar los archivos.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*LottusImpresion*agente.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
New-Item -ItemType Directory -Force -Path $destino | Out-Null
Copy-Item (Join-Path $origen 'agente.py'), (Join-Path $origen 'SumatraPDF.exe') $destino -Force
Copy-Item (Join-Path $origen 'python') $destino -Recurse -Force
if (Test-Path $configOrigen) { Copy-Item $configOrigen $configDestino -Force }

# 3. Guardar la impresora en la configuración y dejarla solo para este usuario.
$config = Get-Content $configDestino -Raw -Encoding UTF8 | ConvertFrom-Json
$config | Add-Member -NotePropertyName cola -NotePropertyValue $cola -Force
$config | ConvertTo-Json -Depth 5 | Set-Content $configDestino -Encoding UTF8
icacls $configDestino /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null

# 4. Que arranque al iniciar sesión (acceso directo en Inicio) y arrancarlo ya.
$python = Join-Path $destino 'python\pythonw.exe'
$agente = Join-Path $destino 'agente.py'
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Lottus Impresion.lnk'))
$acceso.TargetPath = $python
$acceso.Arguments = "`"$agente`""
$acceso.WorkingDirectory = $destino
$acceso.Save()
Start-Process $python -ArgumentList "`"$agente`"" -WorkingDirectory $destino

# 5. Página de prueba.
Write-Host 'Imprimiendo una pagina de prueba...'
& (Join-Path $destino 'python\python.exe') $agente --probar
Write-Host ''
Write-Host 'Listo. Si salio la hoja de prueba, ya se puede imprimir desde la plataforma.' -ForegroundColor Green
Write-Host "Registro: $(Join-Path $destino 'agente.log')"
