#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')][string]$Tipo = 'Debug',
    [string]$Dispositivo,
    [string]$Conectar,
    [string]$Parear,
    [Parameter(Position=0)][string]$CodigoPareamento
)
$ErrorActionPreference = 'Stop'
$javaAnterior = $env:JAVA_HOME
$pathAnterior = $env:PATH
$localAnterior = Get-Location
try {
    $jdk = Get-ChildItem -LiteralPath 'C:\Program Files\Microsoft' -Directory -Filter 'jdk-17*' |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $jdk) { throw 'JDK 17 Microsoft nao encontrado em C:/Program Files/Microsoft/jdk-17*.' }
    $env:JAVA_HOME = $jdk.FullName
    $env:PATH = (Join-Path $jdk.FullName 'bin') + ';' + $env:PATH
    Set-Location -LiteralPath $PSScriptRoot
    $adb = Get-Command adb -ErrorAction SilentlyContinue
    $executavelAdb = if ($adb) { $adb.Source } else { $null }
    if (-not $executavelAdb) {
        $sdk = $env:ANDROID_HOME
        if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
        if (-not $sdk -and (Test-Path -LiteralPath 'local.properties')) {
            $linha = Get-Content -LiteralPath 'local.properties' | Where-Object { $_ -match '^sdk\.dir=' } | Select-Object -First 1
            if ($linha) { $sdk = ($linha.Substring(8) -replace '\\:', ':' -replace '\\\\', '\') }
        }
        if ($sdk) { $executavelAdb = Join-Path $sdk 'platform-tools\adb.exe' }
    }
    if (-not $executavelAdb -or -not (Test-Path -LiteralPath $executavelAdb)) { throw 'adb nao encontrado: configure platform-tools no PATH ou ANDROID_HOME.' }
    if ($Parear) {
        if (-not $CodigoPareamento) { throw 'Use -Parear ip:porta codigo.' }
        & $executavelAdb pair $Parear $CodigoPareamento
        if ($LASTEXITCODE -ne 0) { throw 'Falha no adb pair.' }
    }
    if ($Conectar) {
        & $executavelAdb connect $Conectar
        if ($LASTEXITCODE -ne 0) { throw 'Falha no adb connect.' }
        if (-not $Dispositivo) { $Dispositivo = $Conectar }
    }
    & .\gradlew.bat "assemble$Tipo"
    if ($LASTEXITCODE -ne 0) { throw 'Falha na compilacao Gradle.' }
    $pasta = Join-Path $PSScriptRoot ('app\build\outputs\apk\' + $Tipo.ToLowerInvariant())
    $metadados = Get-Content -LiteralPath (Join-Path $pasta 'output-metadata.json') -Raw | ConvertFrom-Json
    if (@($metadados.elements).Count -ne 1) { throw 'Esperado um APK universal.' }
    $apk = Join-Path $pasta $metadados.elements[0].outputFile
    if ($Tipo -eq 'Release' -and $apk -match '-unsigned\.apk$') { throw 'Release sem assinatura: configure o keystore ou use -Tipo Debug.' }
    $argumentos = @()
    if ($Dispositivo) { $argumentos += @('-s', $Dispositivo) }
    $argumentos += @('install', '-r', $apk)
    & $executavelAdb @argumentos
    if ($LASTEXITCODE -ne 0) { throw 'Falha na instalacao. Confira dispositivo autorizado, assinatura e versionCode.' }
    Write-Output "Instalado: $apk"
} finally {
    Set-Location -LiteralPath $localAnterior.Path
    $env:JAVA_HOME = $javaAnterior
    $env:PATH = $pathAnterior
}
