"""Captura de falhas e verificações de saúde sem derrubar o motor."""

import hashlib
import json
import os
import importlib.metadata
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import traceback as tb
import urllib.request

import registro

REPO = Path(__file__).resolve().parents[1]


def limpar(texto, limite=1000):
    texto = re.sub(r'(?i)(api[_-]?key|token|senha|authorization|secret)\s*[:=]\s*\S+',
                   r'\1=[removido]', str(texto))
    texto = re.sub(r'''(?i)(["']?(?:api[_-]?key|token|senha|authorization|secret)["']?\s*[:=]\s*)["']?[^,}\s]+''',
                   r'\1[removido]', texto)
    texto = re.sub(r'\b(?:sk-|AIza)[\w-]+', '[removido]', texto)
    return texto[:limite]


def assinatura(erro, traceback=None, origem='motor'):
    quadros = tb.extract_tb(traceback) if traceback else []
    nossos = [q for q in quadros if Path(q.filename).resolve().is_relative_to(REPO)]
    quadro = (nossos or quadros)[-1] if quadros else None
    local = f'{Path(quadro.filename).name}:{quadro.name}' if quadro else origem
    return hashlib.sha256(f'{type(erro).__name__}:{local}'.encode()).hexdigest()


def registrar_bug(origem, erro, traceback=None, contexto=None, tipo='bug', banco=registro.BANCO):
    if tipo not in ('bug', 'melhoria'):
        raise ValueError('Tipo deve ser bug ou melhoria')
    try:
        contexto = contexto or {}
        seguro = {k: limpar(v, 200) for k, v in contexto.items()
                  if k in ('pedido', 'motor', 'ferramenta')}
        seguro['origem'] = limpar(origem, 100)
        rastro = ''.join(tb.format_exception(type(erro), erro, traceback)) if traceback else str(erro)
        chave = assinatura(erro, traceback, origem)
        if tipo == 'melhoria':
            chave = hashlib.sha256(('melhoria:' + str(erro)).encode()).hexdigest()
        return registro.salvar_bug(chave, tipo, limpar(erro, 240), limpar(rastro, 8000), seguro, banco)
    except Exception:
        return None


def instalar_hooks():
    if getattr(sys.excepthook, "_secretario", False):
        return
    anterior, anterior_thread = sys.excepthook, threading.excepthook

    def hook(tipo, erro, rastro):
        registrar_bug('excepthook', erro, rastro)
        anterior(tipo, erro, rastro)

    def hook_thread(args):
        registrar_bug('threading', args.exc_value, args.exc_traceback)
        anterior_thread(args)

    hook._secretario = True
    sys.excepthook, threading.excepthook = hook, hook_thread


def importar_quedas(pasta=None, banco=registro.BANCO):
    for arquivo in (Path(pasta) if pasta else REPO / 'voz' / 'sinais').glob('bug_*.json'):
        try:
            dados = json.loads(arquivo.read_text(encoding='utf-8'))
            id = registrar_bug('queda_motor', RuntimeError(limpar(dados, 8000)), banco=banco)
            if id is not None:
                arquivo.unlink()
        except (OSError, ValueError):
            continue


def detectar_sintomas(eventos=None, banco=registro.BANCO):
    eventos = registro.eventos_recentes(banco) if eventos is None else eventos
    motores, vazias, ferramentas = {}, 0, {}
    achados = []
    for ev in eventos:
        autor, texto = ev.get('autor', ''), ev.get('texto', '')
        if autor == 'ERRO':
            chave = (ev.get('motor'), texto)
            motores[chave] = motores.get(chave, 0) + 1
            if motores[chave] == 3:
                achados.append(('motor', texto))
        if autor == 'Transcrição':
            vazias = vazias + 1 if not texto.strip() else 0
            if vazias == 5:
                achados.append(('transcricao', 'Cinco transcrições vazias seguidas.'))
        if autor == 'Ferramenta':
            nome, _, resultado = texto.partition(':')
            ferramentas[nome] = ferramentas.get(nome, 0) + 1 if resultado.strip() == 'erro' else 0
            if ferramentas[nome] == 3:
                achados.append(('ferramenta:' + nome, 'Ferramenta falhou três vezes: ' + nome))
    for origem, resumo in achados:
        # A mesma janela de eventos não deve aumentar a contagem a cada consulta.
        chave = assinatura(RuntimeError(resumo), origem=origem)
        if not any(b['assinatura'] == chave for b in registro.listar_bugs(banco)):
            registrar_bug(origem, RuntimeError(resumo), banco=banco)
    return achados


def verificar_saude(completo=False, microfone=None):
    import backup
    import memoria
    resultado = {}
    verificacoes = {
        'banco': lambda: backup.verificar_banco() == 'ok',
        'cofre': lambda: memoria.COFRE.exists(),
        'disco': lambda: shutil.disk_usage(REPO).free > 2 * 1024 ** 3,
    }

    def ollama():
        with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3) as resposta:
            return resposta.status == 200

    def abrir_microfone():
        import sounddevice
        with sounddevice.InputStream(channels=1):
            return True

    verificacoes.update(ollama=ollama, microfone=microfone or abrir_microfone)
    if completo:
        verificacoes['testes'] = lambda: subprocess.run(
            [sys.executable, '-m', 'pytest', 'voz/tests', '-q'], cwd=REPO,
            capture_output=True, timeout=300, creationflags=0x08000000 if sys.platform == 'win32' else 0).returncode == 0
    for nome, verificar in verificacoes.items():
        try:
            resultado[nome] = bool(verificar())
        except Exception:
            resultado[nome] = False
    for nome, ok in resultado.items():
        if not ok:
            registrar_bug('saude:' + nome, RuntimeError('Verificação de saúde falhou: ' + nome))
    return resultado


def verificar_instalacao():
    """Inspeciona arquivos e comandos sem instalar, abrir dispositivos ou gravar dados."""
    casa = Path.home()
    local = Path(os.environ.get('LOCALAPPDATA', casa / 'AppData' / 'Local'))
    roaming = Path(os.environ.get('APPDATA', casa / 'AppData' / 'Roaming'))
    python = REPO / 'voz' / '.venv' / 'Scripts' / 'python.exe'
    linhas = []

    def conferir(nome, verificar, detalhe='', opcional=False):
        try:
            ok = bool(verificar())
        except Exception as erro:
            ok, detalhe = False, limpar(erro, 200)
        linhas.append({'passo': nome, 'estado': 'ok' if ok else 'ação do usuário',
                       'detalhe': detalhe if not ok else '', 'opcional': opcional})

    # Ollama e Obsidian instalam por usuário em AppData\Local\Programs, fora do PATH.
    programas = local / 'Programs'
    for comando in ('winget', 'py', 'node', 'npm', 'git', 'ollama', 'claude', 'codex'):
        conferir(comando, lambda c=comando: shutil.which(c) or (c == 'ollama' and
                 (programas / 'Ollama/ollama.exe').is_file()), 'Comando ausente no PATH')
    conferir('Python 3.12 / venv', lambda: python.is_file() and sys.version_info[:2] == (3, 12)
             and Path(sys.executable).resolve() == python.resolve(), 'Use o Python 3.12 do venv')

    def dependencias():
        for linha in (REPO / 'voz' / 'requirements.txt').read_text(encoding='utf-8-sig').splitlines():
            if not linha.strip() or linha.startswith('#'):
                continue
            nome, versao = linha.split('==', 1)
            if importlib.metadata.version(nome) != versao:
                return False
        return True

    conferir('Dependências Python', dependencias, 'Execute o passo de requirements')
    conferir('Electron', lambda: (REPO / 'app/node_modules/electron/dist/electron.exe').is_file())
    conferir('Obsidian', lambda: any(p.is_file() for p in (
        programas / 'Obsidian/Obsidian.exe', Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Obsidian/Obsidian.exe')))
    try:
        mcps = json.loads((casa / '.claude.json').read_text(encoding='utf-8-sig')).get('mcpServers', {})
    except (OSError, ValueError):
        mcps = {}
    sentidos = mcps.get('sentidos', {})
    conferir('MCP sentidos', lambda: Path(sentidos.get('command', '')).resolve() == python.resolve()
             and len(sentidos.get('args', [])) == 1
             and Path(sentidos['args'][0]).resolve() == (REPO / 'voz/sentidos_mcp.py').resolve())
    playwright = mcps.get('playwright', {})
    conferir('MCP playwright', lambda: playwright.get('command') in ('npx', 'npx.cmd')
             and '@playwright/mcp@latest' in playwright.get('args', []))  # aceita '-y' antes
    conferir('Chromium', lambda: any((local / 'ms-playwright').glob('chromium-*')))
    for origem, destino in (('skill/SKILL.md', '.claude/skills/secretario/SKILL.md'),
                            ('agente/secretario.md', '.claude/agents/secretario.md')):
        conferir(destino, lambda o=origem, d=destino:
                 (casa / d).read_bytes() == (REPO / 'instalacao' / o).read_bytes())
    cofre = casa / 'Documents/Secretario'
    conferir('Cofre', cofre.is_dir)

    def registro_obsidian():
        dados = json.loads((roaming / 'obsidian/obsidian.json').read_text(encoding='utf-8-sig'))
        return any(Path(v['path']).resolve() == cofre.resolve() for v in dados.get('vaults', {}).values())

    conferir('Registro Obsidian', registro_obsidian)
    conferir('Configuração', lambda: isinstance(json.loads((REPO / 'voz/config.json').read_text(encoding='utf-8-sig')), dict))

    def gemma():
        with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3) as resposta:
            return any(m.get('name') == 'gemma3:4b' for m in json.load(resposta).get('models', []))

    def gemma_baixado():
        # Com o Ollama fechado, o modelo continua instalado: confere o manifesto em disco.
        manifesto = casa / '.ollama/models/manifests/registry.ollama.ai/library/gemma3/4b'
        if manifesto.is_file():
            return True
        return gemma()

    conferir('Gemma 3 4b', gemma_baixado, 'Pode ser pulado com -SemModelos', True)

    def whisper():
        # README/.gitattributes podem faltar no cache sem afetar o modelo.
        cache = Path(os.environ.get('HF_HOME', casa / '.cache/huggingface')) / 'hub'
        return any(cache.glob('models--Systran--faster-whisper-small/snapshots/*/model.bin'))

    conferir('Whisper small', whisper, 'Pode ser pulado com -SemModelos', True)
    conferir('Piper faber', lambda: all((REPO / 'voz/modelos_voz' / ('pt_BR-faber-medium.onnx' + s)).is_file()
                                     for s in ('', '.json')), 'Opcional: -Voz faber', True)
    conferir('JDK 17', lambda: any(Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('Microsoft/jdk-17*/bin/java.exe')),
             'Opcional: -Celular; JAVA_HOME preservado', True)
    sdk = local / 'Android/Sdk'
    for nome in ('cmdline-tools/latest/bin/sdkmanager.bat', 'platform-tools/adb.exe',
                 'platforms/android-35/android.jar', 'build-tools/35.0.0/aapt2.exe'):
        conferir('Android ' + nome, lambda n=nome: (sdk / n).is_file(), 'Opcional: -Celular', True)
    conferir('Tailscale', lambda: shutil.which('tailscale') or
             (Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe').is_file(),
             'Opcional: -Tailscale', True)
    def area_de_trabalho():
        import ctypes
        caminho = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, caminho)  # pode estar no OneDrive
        return Path(caminho.value or casa / 'Desktop')

    def atalho(pasta):
        return any((pasta / nome).is_file() for nome in ('Secretário.lnk', 'Secretario.lnk'))

    def inicia_com_windows():
        import winreg
        if atalho(roaming / 'Microsoft/Windows/Start Menu/Programs/Startup'):
            return True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as chave:
            indice = 0
            while True:
                try:
                    _, valor, _ = winreg.EnumValue(chave, indice)
                except OSError:
                    return False
                if str(REPO / 'app').lower() in str(valor).lower():
                    return True  # item de login do Electron
                indice += 1

    conferir('Atalho na área de trabalho', lambda: atalho(area_de_trabalho()))
    conferir('Iniciar com o Windows', inicia_com_windows)
    return linhas


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instalacao', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.instalacao:
        linhas = verificar_instalacao()
        if args.json:
            print(json.dumps(linhas, ensure_ascii=True))
        else:
            print(f'{"Passo":65} | {"Estado":18} | Detalhe')
            print('-' * 110)
            for linha in linhas:
                print(f'{linha["passo"]:65} | {linha["estado"]:18} | {linha["detalhe"]}')
            print('Ações do usuário: claude (login), codex login e chaves de API nas Configurações.')
        sys.exit(int(any(l['estado'] != 'ok' and not l['opcional'] for l in linhas)))
