"""Captura de falhas e verificações de saúde sem derrubar o motor."""

import hashlib
import json
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
