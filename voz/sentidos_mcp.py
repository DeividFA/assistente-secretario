"""Servidor MCP "sentidos": dá ao Claude microfone, voz, câmera, visão da tela e
controle de mouse/teclado no Windows."""

import ctypes
import json
import os
import time
from datetime import datetime
from pathlib import Path

# Coordenadas em pixels físicos, iguais para a captura de tela e para o mouse.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow
import pyperclip
from mcp.server.fastmcp import FastMCP, Image

from comum import CAPTURAS, Microfone, bip, falar as _falar, transcrever
import delegacao
import provedores
import backup
import vozes
import segundo_plano
import lembretes as armazenamento_lembretes

pyautogui.FAILSAFE = True  # mouse no canto superior esquerdo aborta qualquer ação
pyautogui.PAUSE = 0.15

mcp = FastMCP("sentidos")
_escala = {"fator": 1.0, "x0": 0, "y0": 0}
LEMBRETES = Path(__file__).resolve().parent / "lembretes.json"


@mcp.tool()
def aprender_pronuncia(ouvido: str, correto: str) -> str:
    """Aprende um termo mal reconhecido; protege palavras comuns isoladas."""
    import padrao_fala
    return "Pronúncia aprendida." if padrao_fala.aprender_pronuncia(ouvido, correto) else "Correção recusada: palavra comum ou trecho vazio."


def _arquivo(prefixo):
    return CAPTURAS / f"{prefixo}_{datetime.now():%Y%m%d_%H%M%S}.jpg"


@mcp.tool()
def vozes_disponiveis() -> list[dict]:
    """Lista vozes locais e online; Edge envia o texto à Microsoft."""
    resultado = vozes.listar()
    import config
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            sapi = win32com.client.Dispatch('SAPI.SpVoice')
            import locale
            instalados = set()
            for token in sapi.GetVoices():
                for codigo in token.GetAttribute('Language').split(';'):
                    nome = locale.windows_locale.get(int(codigo, 16), '')
                    instalados.add(nome.split('_')[0])
            for idioma in config.carregar().get('idiomas', ['pt']):
                if idioma.split('-')[0] not in instalados:
                    resultado.append({'id': 'windows:' + idioma, 'idioma': idioma,
                                      'aviso': 'Não há voz do Windows para este idioma. Instale em Configurações > Hora e idioma > Fala.'})
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        resultado.append({'id': 'windows', 'aviso': 'Não foi possível consultar os idiomas das vozes do Windows.'})
    return resultado


@mcp.tool()
def baixar_voz(id: str) -> str:
    """Baixa uma voz Piper do catálogo."""
    vozes.baixar(id)
    return "Voz baixada."


@mcp.tool()
def usar_voz(id: str) -> str:
    """Escolhe a voz; Edge usa internet e envia o texto à Microsoft."""
    vozes.usar(id)
    return "Voz alterada."


@mcp.tool()
def delegar(agente: str, tarefa: str, pasta: str = "") -> dict:
    """Delega trabalho completo e autocontido a um agente CLI em segundo plano."""
    id = delegacao.iniciar(agente, tarefa, pasta or None)
    return {"id": id, "texto": f"Trabalho iniciado com {agente}. Consulte resultado_delegacao."}


@mcp.tool()
def resultado_delegacao(id: str) -> dict:
    """Consulta estado, resposta e ferramentas de um trabalho delegado."""
    return delegacao.estado(id)


@mcp.tool()
def cancelar_delegacao(id: str) -> dict:
    """Cancela um trabalho delegado e encerra a árvore do agente."""
    return delegacao.cancelar(id)


@mcp.tool()
def agentes_disponiveis() -> list[dict]:
    """Lista os agentes CLI e informa sua disponibilidade e motivo."""
    return [agente for agente in provedores.listar() if agente["tipo"] == "cli"]


@mcp.tool()
def reiniciar_secretario(completo: bool = False) -> str:
    """Reinicia o motor do secretário; completo=True reinicia também o app."""
    sinais = Path(__file__).resolve().parent / "sinais"
    sinais.mkdir(parents=True, exist_ok=True)
    temporario = sinais / "reiniciar.tmp"
    temporario.write_text("completo" if completo else "motor", encoding="utf-8")
    temporario.replace(sinais / "reiniciar")
    return "Reinício solicitado."


@mcp.tool()
def listar_lembretes() -> list[dict]:
    """Lista os lembretes agendados, incluindo os já feitos."""
    return armazenamento_lembretes.listar(LEMBRETES)


@mcp.tool()
def lembrete(quando: str, texto: str) -> str:
    """Agenda um lembrete no horário local, em ISO AAAA-MM-DDTHH:MM."""
    try:
        data = datetime.strptime(quando, "%Y-%m-%dT%H:%M")
    except ValueError:
        return "Data inválida. Use AAAA-MM-DDTHH:MM."
    if data.isoformat(timespec="minutes") != quando:
        return "Data inválida. Use AAAA-MM-DDTHH:MM."
    armazenamento_lembretes.adicionar(quando, texto, arquivo=LEMBRETES)
    return f"Lembrete agendado para {quando}."


@mcp.tool()
def ouvir(espera_max_segundos: int = 10) -> str:
    """Liga o microfone, espera o usuário falar e devolve a transcrição em português.
    Use somente quando o usuário pediu para ser ouvido (ex.: "me escuta", "vou ditar")."""
    mic = Microfone()
    try:
        bip()
        audio = mic.gravar_fala(espera_max=espera_max_segundos)
    finally:
        mic.fechar()
    if audio is None:
        return "(ninguém falou)"
    return transcrever(audio) or "(não entendi o que foi dito)"


@mcp.tool()
def falar(texto: str) -> str:
    """Fala o texto em voz alta (voz pt-BR do Windows)."""
    _falar(texto)
    return "falado"


def salvar_foto(camera: int = 0) -> Path:
    """Salva uma foto da webcam e devolve seu caminho."""
    cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Câmera {camera} não abriu. Tente outro número (0, 1, 2).")
    try:
        for _ in range(8):  # deixa a exposição automática estabilizar
            cap.read()
            time.sleep(0.05)
        ok, quadro = cap.read()
    finally:
        cap.release()
    if not ok:
        raise RuntimeError("Não consegui capturar a imagem.")
    caminho = _arquivo("camera")
    cv2.imwrite(str(caminho), quadro, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return caminho


def salvar_tela(monitor: int = 1) -> Path:
    """Salva a tela e mantém a escala usada pelas ações do mouse."""
    with mss.mss() as sct:
        mon = sct.monitors[monitor]
        img = np.array(sct.grab(mon))[:, :, :3]
    altura, largura = img.shape[:2]
    fator = min(1.0, 1568 / largura)
    if fator < 1.0:
        img = cv2.resize(img, (int(largura * fator), int(altura * fator)), interpolation=cv2.INTER_AREA)
    _escala.update(fator=fator, x0=mon["left"], y0=mon["top"])
    caminho = _arquivo("tela")
    cv2.imwrite(str(caminho), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    _escala["descricao"] = f"Tela {largura}x{altura}, imagem {img.shape[1]}x{img.shape[0]}. Salva em {caminho}"
    return caminho


@mcp.tool()
def foto_camera(camera: int = 0):
    """Tira uma foto com a webcam e devolve a imagem. Use SOMENTE quando o usuário pedir
    explicitamente para usar a câmera nesta tarefa. Câmeras detectadas: 0 e 2."""
    try:
        caminho = salvar_foto(camera)
    except RuntimeError as erro:
        return str(erro)
    return [f"Foto salva em {caminho}", Image(path=str(caminho))]


@mcp.tool()
def captura_tela(monitor: int = 1):
    """Tira um print da tela (monitor 1 = principal) e devolve a imagem. As coordenadas
    que você ler nesta imagem podem ser passadas direto para clicar()."""
    caminho = salvar_tela(monitor)
    return [_escala["descricao"], Image(path=str(caminho))]


def _real(x, y):
    f = _escala["fator"]
    return int(x / f) + _escala["x0"], int(y / f) + _escala["y0"]


@mcp.tool()
def capturar_janela(titulo: str):
    """Captura uma janela restaurada por trás das outras, sem trocar o foco."""
    try:
        caminho = segundo_plano.capturar_janela(titulo, _arquivo("janela"))
        return [f"Janela salva em {caminho}", Image(path=str(caminho))]
    except Exception as erro:
        return str(erro)


@mcp.tool()
def ler_janela(titulo: str, limite: int = 4000) -> str:
    """Lista elementos UI Automation com índices a partir de zero, sem trocar o foco."""
    try:
        return segundo_plano.ler_janela(titulo, limite)
    except Exception as erro:
        return f"Não consegui ler por UI Automation: {erro}"


@mcp.tool()
def preencher_campo(titulo: str, alvo: str, texto: str) -> str:
    """Preenche via ValuePattern; alvo é índice, nome ou automation_id da última leitura."""
    try:
        return segundo_plano.preencher_campo(titulo, alvo, texto)
    except Exception as erro:
        return f"Não consegui preencher por UI Automation: {erro}"


@mcp.tool()
def acionar(titulo: str, alvo: str) -> str:
    """Aciona Invoke, Toggle ou SelectionItem, sem simular mouse ou teclado."""
    try:
        return segundo_plano.acionar(titulo, alvo)
    except Exception as erro:
        return f"Não consegui acionar por UI Automation: {erro}"


@mcp.tool()
@segundo_plano.fisica
def clicar(x: int, y: int, botao: str = "left", cliques: int = 1) -> str:
    """Clica na posição (x, y) da última captura_tela(). botao: left, right ou middle."""
    rx, ry = _real(x, y)
    pyautogui.click(rx, ry, clicks=cliques, button=botao)
    return f"clicado em ({rx}, {ry})"


@mcp.tool()
@segundo_plano.fisica
def arrastar(x1: int, y1: int, x2: int, y2: int) -> str:
    """Arrasta o mouse de (x1, y1) até (x2, y2), em coordenadas da última captura_tela()."""
    a, b = _real(x1, y1), _real(x2, y2)
    pyautogui.moveTo(*a)
    pyautogui.dragTo(*b, duration=0.4)
    return "arrastado"


@mcp.tool()
@segundo_plano.fisica
def digitar(texto: str, enter: bool = False) -> str:
    """Digita o texto no campo que está em foco (aceita acentos). enter=True aperta Enter no fim."""
    pyperclip.copy(texto)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)  # deixa o aplicativo consumir o texto antes de restaurar
    if enter:
        pyautogui.press("enter")
    return "digitado"


@mcp.tool()
@segundo_plano.fisica
def teclas(combinacao: str) -> str:
    """Pressiona uma tecla ou atalho, ex.: "enter", "ctrl+c", "alt+tab", "win+d", "ctrl+shift+esc"."""
    partes = [p.strip().lower() for p in combinacao.split("+")]
    pyautogui.hotkey(*partes)
    return f"pressionado {combinacao}"


@mcp.tool()
@segundo_plano.fisica
def rolar(quantidade: int) -> str:
    """Rola a tela na posição do mouse. Positivo sobe, negativo desce (1 = um "clique" da roda)."""
    pyautogui.scroll(quantidade * 120)
    return "rolado"


@mcp.tool()
def abrir(alvo: str) -> str:
    """Abre um programa, arquivo, pasta ou URL, ex.: "notepad", "calc", a pasta Documents do usuário,
    "https://gov.br"."""
    os.startfile(alvo)
    return f"abrindo {alvo}"


@mcp.tool()
def janelas() -> list[str]:
    """Lista os títulos das janelas abertas."""
    return [t for t in pygetwindow.getAllTitles() if t.strip()]


@mcp.tool()
@segundo_plano.fisica
def focar_janela(titulo_parcial: str) -> str:
    """Traz para frente a primeira janela cujo título contém o texto informado."""
    for janela in pygetwindow.getAllWindows():
        if titulo_parcial.lower() in janela.title.lower():
            if janela.isMinimized:
                janela.restore()
            try:
                janela.activate()
            except Exception:
                pyautogui.press("alt")  # o Windows só deixa trocar o foco após uma tecla
                janela.activate()
            return f"janela em foco: {janela.title}"
    return "nenhuma janela encontrada com esse título"


@mcp.tool()
def fazer_backup(motivo: str = "pedido") -> str:
    """Cria uma cópia verificada do SQLite e dos dados do secretário."""
    return backup.fazer_backup(motivo)


@mcp.tool()
def listar_backups() -> list[dict]:
    """Lista as cópias disponíveis, mais recentes primeiro."""
    return backup.listar_backups()


@mcp.tool()
def restaurar_backup(nome: str = "") -> str:
    """Explica como restaurar. A restauração em si é feita pelo motor de voz, que precisa
    estar sem tarefas e pede a confirmação do Deivid."""
    return ("Não restauro daqui: o motor de voz está usando o banco. Peça ao Deivid para "
            "dizer ou digitar 'restaura o backup'; o motor mostra qual backup e pede confirmação.")



@mcp.tool()
def listar_bugs() -> list[dict]:
    """Lista problemas e melhorias registrados pelo secretário."""
    import registro
    return registro.listar_bugs()


@mcp.tool()
def detalhe_bug(id: int) -> dict:
    """Mostra o contexto e traceback de um problema."""
    import registro
    return registro.detalhe_bug(id) or {}


@mcp.tool()
def corrigir_bug(id: int, diretriz: str = '') -> str:
    """Solicita ao motor a confirmação do Deivid para este bug; não aprova pelo agente."""
    pasta = Path(__file__).resolve().parent / 'sinais'
    pasta.mkdir(exist_ok=True)
    (pasta / f'corrigir_{id}.json').write_text(
        json.dumps({'id': id, 'diretriz': diretriz}, ensure_ascii=False), encoding='utf-8')
    return 'O motor pedirá a aprovação explícita do Deivid para este problema.'


if __name__ == "__main__":
    mcp.run()
