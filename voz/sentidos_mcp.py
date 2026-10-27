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

pyautogui.FAILSAFE = True  # mouse no canto superior esquerdo aborta qualquer ação
pyautogui.PAUSE = 0.15

mcp = FastMCP("sentidos")
_escala = {"fator": 1.0, "x0": 0, "y0": 0}
LEMBRETES = Path(__file__).resolve().parent / "lembretes.json"


def _arquivo(prefixo):
    return CAPTURAS / f"{prefixo}_{datetime.now():%Y%m%d_%H%M%S}.jpg"


@mcp.tool()
def listar_lembretes() -> list[dict]:
    """Lista os lembretes agendados, incluindo os já feitos."""
    try:
        return json.loads(LEMBRETES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


@mcp.tool()
def lembrete(quando: str, texto: str) -> str:
    """Agenda um lembrete no horário local, em ISO AAAA-MM-DDTHH:MM."""
    try:
        data = datetime.strptime(quando, "%Y-%m-%dT%H:%M")
    except ValueError:
        return "Data inválida. Use AAAA-MM-DDTHH:MM."
    if data.isoformat(timespec="minutes") != quando:
        return "Data inválida. Use AAAA-MM-DDTHH:MM."
    lembretes = listar_lembretes()
    lembretes.append({"quando": quando, "texto": texto, "feito": False})
    temporario = LEMBRETES.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(lembretes, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(LEMBRETES)
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
def clicar(x: int, y: int, botao: str = "left", cliques: int = 1) -> str:
    """Clica na posição (x, y) da última captura_tela(). botao: left, right ou middle."""
    rx, ry = _real(x, y)
    pyautogui.click(rx, ry, clicks=cliques, button=botao)
    return f"clicado em ({rx}, {ry})"


@mcp.tool()
def arrastar(x1: int, y1: int, x2: int, y2: int) -> str:
    """Arrasta o mouse de (x1, y1) até (x2, y2), em coordenadas da última captura_tela()."""
    a, b = _real(x1, y1), _real(x2, y2)
    pyautogui.moveTo(*a)
    pyautogui.dragTo(*b, duration=0.4)
    return "arrastado"


@mcp.tool()
def digitar(texto: str, enter: bool = False) -> str:
    """Digita o texto no campo que está em foco (aceita acentos). enter=True aperta Enter no fim."""
    pyperclip.copy(texto)
    pyautogui.hotkey("ctrl", "v")
    if enter:
        pyautogui.press("enter")
    return "digitado"


@mcp.tool()
def teclas(combinacao: str) -> str:
    """Pressiona uma tecla ou atalho, ex.: "enter", "ctrl+c", "alt+tab", "win+d", "ctrl+shift+esc"."""
    partes = [p.strip().lower() for p in combinacao.split("+")]
    pyautogui.hotkey(*partes)
    return f"pressionado {combinacao}"


@mcp.tool()
def rolar(quantidade: int) -> str:
    """Rola a tela na posição do mouse. Positivo sobe, negativo desce (1 = um "clique" da roda)."""
    pyautogui.scroll(quantidade * 120)
    return "rolado"


@mcp.tool()
def abrir(alvo: str) -> str:
    """Abre um programa, arquivo, pasta ou URL, ex.: "notepad", "calc", "C:\\Users\\deivi\\Documents",
    "https://gov.br"."""
    os.startfile(alvo)
    return f"abrindo {alvo}"


@mcp.tool()
def janelas() -> list[str]:
    """Lista os títulos das janelas abertas."""
    return [t for t in pygetwindow.getAllTitles() if t.strip()]


@mcp.tool()
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


if __name__ == "__main__":
    mcp.run()
