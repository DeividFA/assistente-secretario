#requires -Version 5.1
[CmdletBinding()]
param([switch]$Verificar, [switch]$SemModelos, [ValidateSet('faber')][string]$Voz,
      [switch]$Celular, [switch]$Tailscale)
$ErrorActionPreference = 'Stop'
$Raiz = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Raiz 'voz\.venv\Scripts\python.exe'
$Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$Resultados = New-Object System.Collections.Generic.List[object]
function Executar($Programa, [string[]]$Argumentos) {
    # PowerShell 5.1 remove aspas internas dos argumentos nativos.
    # O codigo Python passa por stdin para preservar suas strings.
    if ($Argumentos.Count -ge 2 -and $Argumentos[0] -eq '-c') {
        $codePython = $Argumentos[1]
        $suite = @($Argumentos | Select-Object -Skip 2)
        $codePython | & $Programa - @suite
    } else { & $Programa @Argumentos }
    if ($LASTEXITCODE -ne 0) { throw "$Programa terminou com codigo $LASTEXITCODE" }
}
function Passo($Nome, [scriptblock]$Conferir, [scriptblock]$Instalar) {
    try {
        if (& $Conferir) { $estado = 'ok' }
        else { & $Instalar; if (-not (& $Conferir)) { throw 'Verificacao posterior falhou' }; $estado = 'instalado' }
        $detalhe = ''
    } catch { $estado = 'falhou'; $detalhe = $_.Exception.Message }
    $linha = [pscustomobject]@{Passo=$Nome; Estado=$estado; Detalhe=$detalhe}
    $Resultados.Add($linha)
    $linha | ConvertTo-Json -Compress | Add-Content (Join-Path $PSScriptRoot 'instalar.log') -Encoding UTF8
}
function Pacote($Id) {
    $lista = & winget list --id $Id --exact --accept-source-agreements --disable-interactivity 2>$null
    return $LASTEXITCODE -eq 0 -and ($lista -join "`n") -match [regex]::Escape($Id)
}
function Instalar-Pacote($Id) {
    Executar winget @('install','--id',$Id,'--exact','--accept-package-agreements','--accept-source-agreements','--disable-interactivity')
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
# Sai antes de qualquer escrita, winget, download ou instalacao.
if ($Verificar) {
    if (Test-Path $Python) { & $Python (Join-Path $Raiz 'voz\diagnostico.py') --instalacao; exit $LASTEXITCODE }
    [pscustomobject]@{Passo='Python do venv'; Estado='acao do usuario'; Detalhe='Execute instalar.ps1'} | Format-Table -AutoSize
    exit 1
}
Passo 'winget' { [bool](Get-Command winget -ErrorAction SilentlyContinue) } { throw 'Instale o App Installer da Microsoft Store.' }
foreach ($id in @('Python.Python.3.12','OpenJS.NodeJS.LTS','Git.Git','Ollama.Ollama','Obsidian.Obsidian')) {
    Passo $id { Pacote $id } { Instalar-Pacote $id }
}
Passo 'venv Python 3.12' {
    if (-not (Test-Path $Python)) { return $false }
    'import sys; sys.exit(sys.version_info[:2] != (3, 12))' | & $Python -
    $LASTEXITCODE -eq 0
} {
    if (Test-Path $Python) { throw 'O venv existente usa outro Python. Preserve-o antes de recriar com Python 3.12.' }
    Executar py @('-3.12','-m','venv',(Join-Path $Raiz 'voz\.venv'),'--without-pip')
}
Passo 'pip' { & $Python -m pip --version 2>$null | Out-Null; $LASTEXITCODE -eq 0 } {
    & $Python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        $base = & $Python -c 'import sys; print(sys.base_prefix)'
        $roda = Get-ChildItem (Join-Path $base 'Lib\ensurepip\_bundled') -Filter 'pip-*.whl' | Select-Object -First 1
        if (-not $roda) { throw 'Roda bundled do pip nao encontrada' }
        Executar $Python @('-c','import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("pip",run_name="__main__")',$roda.FullName,'install','pip')
    }
}
$Requisitos = Join-Path $Raiz 'voz\requirements.txt'
$MarcaPip = Join-Path $Raiz 'voz\.venv\requirements.sha256'
Passo 'dependencias Python' {
    (Test-Path $MarcaPip) -and ((Get-Content $MarcaPip -Raw).Trim() -eq (Get-FileHash $Requisitos).Hash)
} {
    Executar $Python @('-m','pip','install','-r',$Requisitos)
    (Get-FileHash $Requisitos).Hash | Set-Content $MarcaPip
}
$App = Join-Path $Raiz 'app'
$MarcaNpm = Join-Path $App 'node_modules\.secretario-lock'
Passo 'dependencias Electron' {
    (Test-Path $MarcaNpm) -and (Test-Path (Join-Path $App 'node_modules\electron\dist\electron.exe')) -and ((Get-Content $MarcaNpm -Raw).Trim() -eq (Get-FileHash (Join-Path $App 'package-lock.json')).Hash)
} {
    Push-Location $App
    try { Executar npm.cmd @('ci'); (Get-FileHash 'package-lock.json').Hash | Set-Content $MarcaNpm } finally { Pop-Location }
}
foreach ($cli in @(@('claude','@anthropic-ai/claude-code'),@('codex','@openai/codex'))) {
    Passo $cli[0] { [bool](Get-Command $cli[0] -ErrorAction SilentlyContinue) } { Executar npm.cmd @('install','-g',$cli[1]) }
}
function Config-Mcp($Nome) {
    $arquivo = Join-Path $HOME '.claude.json'
    if (Test-Path $arquivo) { return (Get-Content $arquivo -Raw | ConvertFrom-Json).mcpServers.$Nome }
}
function Mesmo-Caminho($A, $B) {
    if (-not $A -or -not $B) { return $false }
    try { return [IO.Path]::GetFullPath($A).TrimEnd('\') -eq [IO.Path]::GetFullPath($B).TrimEnd('\') }
    catch { return $false }
}
$Sentidos = Join-Path $Raiz 'voz\sentidos_mcp.py'
foreach ($nome in @('playwright','sentidos')) {
    Passo "MCP $nome" {
        $m = Config-Mcp $nome
        if ($nome -eq 'sentidos') { return $m -and (Mesmo-Caminho $m.command $Python) -and @($m.args).Count -eq 1 -and (Mesmo-Caminho $m.args[0] $Sentidos) }
        return $m -and $m.command -in @('npx','npx.cmd') -and (@($m.args) -join ' ') -eq '@playwright/mcp@latest'
    } {
        if (Config-Mcp $nome) { Executar claude @('mcp','remove','-s','user',$nome) }
        if ($nome -eq 'sentidos') { Executar claude @('mcp','add','-s','user','sentidos','--',$Python,$Sentidos) }
        else { Executar claude @('mcp','add','-s','user','playwright','--','npx','@playwright/mcp@latest') }
    }
}
Passo 'Chromium Playwright' { @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'ms-playwright') -Filter 'chromium-*' -ErrorAction SilentlyContinue).Count -gt 0 } {
    Executar npx.cmd @('--yes','playwright','install','chromium')
}
foreach ($copia in @(@('skill\SKILL.md','.claude\skills\secretario\SKILL.md'),@('agente\secretario.md','.claude\agents\secretario.md'))) {
    $origem = Join-Path $PSScriptRoot $copia[0]; $destino = Join-Path $HOME $copia[1]
    Passo $copia[0] { (Test-Path $destino) -and (Get-FileHash $origem).Hash -eq (Get-FileHash $destino).Hash } {
        New-Item (Split-Path $destino) -ItemType Directory -Force | Out-Null
        if (Test-Path $destino) { Copy-Item $destino ($destino + '.' + (Get-Date -Format 'yyyyMMddHHmmssfff') + '.bak') }
        Copy-Item $origem $destino
    }
}
$Cofre = Join-Path $HOME 'Documents\Secretario'
Passo 'cofre' { Test-Path $Cofre } {
    New-Item (Split-Path $Cofre) -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'cofre_modelo') $Cofre -Recurse
}
$Obsidian = Join-Path $env:APPDATA 'obsidian\obsidian.json'
function Ler-Obsidian {
    if (Test-Path $Obsidian) { return Get-Content $Obsidian -Raw | ConvertFrom-Json }
    return [pscustomobject]@{vaults=[pscustomobject]@{}}
}
Passo 'registro Obsidian' { $o = Ler-Obsidian; @($o.vaults.PSObject.Properties | Where-Object { Mesmo-Caminho $_.Value.path $Cofre }).Count -gt 0 } {
    $o = Ler-Obsidian
    if (-not $o.vaults) { $o | Add-Member -NotePropertyName vaults -NotePropertyValue ([pscustomobject]@{}) -Force }
    $o.vaults | Add-Member -NotePropertyName ([guid]::NewGuid().ToString('N').Substring(0,16)) -NotePropertyValue ([pscustomobject]@{path=$Cofre;ts=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();open=$true})
    New-Item (Split-Path $Obsidian) -ItemType Directory -Force | Out-Null
    if (Test-Path $Obsidian) { Copy-Item $Obsidian ($Obsidian + '.' + (Get-Date -Format 'yyyyMMddHHmmssfff') + '.bak') }
    $o | ConvertTo-Json -Depth 50 | Set-Content $Obsidian -Encoding UTF8
}
if (-not $SemModelos) {
    Passo 'Gemma' { $modelos = & ollama list 2>$null; $LASTEXITCODE -eq 0 -and ($modelos -join "`n") -match 'gemma3:4b' } { Executar ollama @('pull','gemma3:4b') }
    Passo 'Whisper small' { 'from huggingface_hub import snapshot_download; snapshot_download("Systran/faster-whisper-small",local_files_only=True)' | & $Python - 2>$null | Out-Null; $LASTEXITCODE -eq 0 } {
        Executar $Python @('-c','from huggingface_hub import snapshot_download; snapshot_download("Systran/faster-whisper-small")')
    }
    if ($Voz) {
        Passo 'Piper faber' { (Test-Path (Join-Path $Raiz 'voz\modelos_voz\pt_BR-faber-medium.onnx')) -and (Test-Path (Join-Path $Raiz 'voz\modelos_voz\pt_BR-faber-medium.onnx.json')) } {
            Push-Location (Join-Path $Raiz 'voz')
            try { Executar $Python @('-c','import vozes,urllib.request; [(p.parent.mkdir(parents=True,exist_ok=True),urllib.request.urlretrieve(u,p)) for u,p in zip(vozes.urls("piper:pt_BR-faber-medium"),vozes.caminhos("piper:pt_BR-faber-medium")) if not p.exists()]') } finally { Pop-Location }
        }
    }
}
Passo 'config.json' { Test-Path (Join-Path $Raiz 'voz\config.json') } { Copy-Item (Join-Path $Raiz 'voz\config.exemplo.json') (Join-Path $Raiz 'voz\config.json') }
# O app já se registra para iniciar com o Windows (item de login do Electron, chave Run);
# um atalho em Inicializar só é criado se esse registro não existir, para não abrir duas vezes.
$runApp = @((Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue).PSObject.Properties |
    Where-Object { "$($_.Value)" -like "*$App*" }).Count -gt 0
$pastas = @([Environment]::GetFolderPath('Desktop'))
if (-not $runApp) { $pastas += [Environment]::GetFolderPath('Startup') }
foreach ($pasta in $pastas) {
    $existente = @('Secretário.lnk','Secretario.lnk') | ForEach-Object { Join-Path $pasta $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    $atalho = if ($existente) { $existente } else { Join-Path $pasta 'Secretário.lnk' }
    $electron = Join-Path $App 'node_modules\electron\dist\electron.exe'
    Passo "atalho $pasta" { if (-not (Test-Path $atalho)) { return $false }; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($atalho); Mesmo-Caminho $s.TargetPath $electron } {
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($atalho)
        $s.TargetPath = $electron; $s.Arguments = '"' + $App + '" --oculto'; $s.WorkingDirectory = $App; $s.Save()
    }
}
if ($Celular) {
    Passo 'JDK 17' { Pacote 'Microsoft.OpenJDK.17' } { Instalar-Pacote 'Microsoft.OpenJDK.17' }
    $Jdk = Get-ChildItem (Join-Path $env:ProgramFiles 'Microsoft') -Directory -Filter 'jdk-17*' -ErrorAction SilentlyContinue | Select-Object -First 1
    Passo 'Android command-line tools' { Test-Path (Join-Path $Sdk 'cmdline-tools\latest\bin\sdkmanager.bat') } {
        $temporario = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
        New-Item $temporario -ItemType Directory | Out-Null
        Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip' -OutFile (Join-Path $temporario 'tools.zip') -UseBasicParsing
        Expand-Archive (Join-Path $temporario 'tools.zip') (Join-Path $temporario 'extraido')
        New-Item (Join-Path $Sdk 'cmdline-tools') -ItemType Directory -Force | Out-Null
        Move-Item (Join-Path $temporario 'extraido\cmdline-tools') (Join-Path $Sdk 'cmdline-tools\latest')
    }
    Passo 'Android SDK 35' { (Test-Path (Join-Path $Sdk 'platform-tools\adb.exe')) -and (Test-Path (Join-Path $Sdk 'platforms\android-35\android.jar')) -and (Test-Path (Join-Path $Sdk 'build-tools\35.0.0\aapt2.exe')) } {
        if (-not $Jdk) { throw 'JDK 17 nao encontrado em Program Files\Microsoft' }
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $env:ComSpec
        $info.Arguments = '/d /s /c ""' + (Join-Path $Sdk 'cmdline-tools\latest\bin\sdkmanager.bat') + '" --sdk_root="' + $Sdk + '" "platform-tools" "platforms;android-35" "build-tools;35.0.0""'
        # Somente o processo filho recebe JAVA_HOME. A sessao e o usuario sao preservados.
        $info.UseShellExecute = $false; $info.EnvironmentVariables['JAVA_HOME'] = $Jdk.FullName
        $info.RedirectStandardInput = $true
        $info.CreateNoWindow = $true
        $processo = [Diagnostics.Process]::Start($info)
        for ($i = 0; $i -lt 100; $i++) {
            try { $processo.StandardInput.WriteLine('y') } catch [System.IO.IOException] { break }
        }
        $processo.StandardInput.Close(); $processo.WaitForExit()
        if ($processo.ExitCode -ne 0) { throw 'sdkmanager falhou; confira as licencas Android.' }
    }
}
if ($Tailscale) { Passo 'Tailscale' { Pacote 'Tailscale.Tailscale' } { Instalar-Pacote 'Tailscale.Tailscale' } }
$Resultados.Add([pscustomobject]@{Passo='Logins e chaves'; Estado='acao do usuario'; Detalhe='claude; codex login; chaves de API nas Configuracoes'})
if ($Tailscale) { $Resultados.Add([pscustomobject]@{Passo='Conectar Tailscale'; Estado='acao do usuario'; Detalhe='Entrar na conta pelo aplicativo'}) }
$Resultados | Format-Table -AutoSize -Wrap
Write-Host 'Acoes do usuario: claude (login), codex login, chaves de API na tela Configuracoes; conectar Tailscale se escolhido.'
if (Test-Path $Python) { & $Python (Join-Path $Raiz 'voz\diagnostico.py') --instalacao }
if (@($Resultados | Where-Object Estado -eq 'falhou').Count) { exit 1 }
