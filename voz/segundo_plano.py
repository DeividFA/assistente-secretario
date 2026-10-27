"""Automação sem disputar mouse e teclado com o Deivid."""

import ctypes
import json
import threading
import time
from contextlib import contextmanager
from functools import wraps
from threading import RLock

OCUPADO = "O Deivid está usando o computador; não interrompi."
_trava = RLock()


# Instante (GetTickCount) até o qual a última entrada foi injetada por nós: as teclas e
# cliques do próprio agente não contam como uso do Deivid.
_nossa_ate = 0


def _ticks():
    return ctypes.windll.kernel32.GetTickCount() & 0xffffffff


def _ultima_entrada():
    class UltimaEntrada(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]

    entrada = UltimaEntrada()
    entrada.cbSize = ctypes.sizeof(entrada)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(entrada)):
        raise OSError("Não consegui consultar a última entrada do usuário.")
    return entrada.dwTime


def ocioso_ha():
    return ((_ticks() - _ultima_entrada()) & 0xffffffff) / 1000


def entrada_foi_nossa():
    return bool(_nossa_ate) and ((_nossa_ate - _ultima_entrada()) & 0xffffffff) < 0x80000000


def esperar_vez(min_ocioso=2.0, max_espera=120):
    fim = time.monotonic() + max_espera
    while True:
        if ocioso_ha() >= min_ocioso or entrada_foi_nossa():
            return True
        restante = fim - time.monotonic()
        if restante <= 0:
            return False
        time.sleep(min(0.1, restante))


def _win32():
    import win32api
    import win32clipboard
    import win32gui
    return win32gui, win32clipboard, win32api


@contextmanager
def restaurando_estado(foco=True):
    """foco=False deixa a janela da frente como a ação deixou (ver `fisica`)."""
    gui, clipboard, api = _win32()
    janela = gui.GetForegroundWindow() if foco else None
    cursor = api.GetCursorPos()
    formatos = []
    clipboard.OpenClipboard()
    try:
        formato = clipboard.EnumClipboardFormats(0)
        while formato:
            # Handles e listas de arquivos exigem cópia especial; não arriscar os dados.
            if formato in (2, 3, 9, 14, 15, 17):
                raise RuntimeError("Área de transferência com formato não restaurável; não agi.")
            dados = clipboard.GetClipboardData(formato)
            if not isinstance(dados, (str, bytes)):
                raise RuntimeError("Não consegui preservar a área de transferência; não agi.")
            formatos.append((formato, dados))
            formato = clipboard.EnumClipboardFormats(formato)
    finally:
        clipboard.CloseClipboard()
    try:
        yield
    finally:
        try:
            clipboard.OpenClipboard()
            try:
                clipboard.EmptyClipboard()
                for formato, dados in formatos:
                    clipboard.SetClipboardData(formato, dados)
            finally:
                clipboard.CloseClipboard()
        finally:
            try:
                api.SetCursorPos(cursor)
            finally:
                if janela and gui.IsWindow(janela) and gui.GetForegroundWindow() != janela:
                    gui.SetForegroundWindow(janela)


# Sequência de ações físicas (ex.: focar_janela → digitar → teclas): a janela da frente
# só volta para a do Deivid depois de SEQUENCIA s sem ações. Devolver o foco a cada ação
# faria o `digitar` seguinte colar o texto na janela dele.
SEQUENCIA = 5.0
_sequencia = {"janela": None, "timer": None}


def _encerrar_sequencia():
    with _trava:
        janela, _sequencia["janela"], _sequencia["timer"] = _sequencia["janela"], None, None
        # Se ele mexeu depois da nossa última ação, ele assumiu: não puxar o foco.
        if not janela or not entrada_foi_nossa():
            return
        try:
            gui = _win32()[0]
            if gui.IsWindow(janela) and gui.GetForegroundWindow() != janela:
                gui.SetForegroundWindow(janela)
        except Exception:
            pass


def fisica(funcao):
    @wraps(funcao)
    def protegida(*args, **kwargs):
        global _nossa_ate
        with _trava:
            if not esperar_vez():
                return OCUPADO
            if _sequencia["timer"] is not None:
                _sequencia["timer"].cancel()
            elif _sequencia["janela"] is None:
                _sequencia["janela"] = _win32()[0].GetForegroundWindow()
            try:
                with restaurando_estado(foco=False):
                    return funcao(*args, **kwargs)
            finally:
                _nossa_ate = _ticks() + 300  # a entrada injetada chega um pouco depois
                _sequencia["timer"] = threading.Timer(SEQUENCIA, _encerrar_sequencia)
                _sequencia["timer"].daemon = True
                _sequencia["timer"].start()
    return protegida


def _janela(titulo):
    from pywinauto import Desktop
    janelas = [j for j in Desktop(backend="uia").windows()
               if titulo.casefold() in j.window_text().casefold()]
    exatas = [j for j in janelas if j.window_text().casefold() == titulo.casefold()]
    janelas = exatas or janelas
    if len(janelas) != 1:
        raise RuntimeError("Informe um título que identifique uma única janela.")
    return janelas[0]


def _elementos(janela):
    elementos = janela.descendants()
    if not elementos:
        raise RuntimeError("O aplicativo não expõe elementos de UI Automation; use as ferramentas físicas.")
    return elementos


def _resolver_alvo(elementos, alvo):
    if isinstance(alvo, int) or (isinstance(alvo, str) and alvo.isdecimal()):
        indice = int(alvo)
        if 0 <= indice < len(elementos):
            return elementos[indice]
        raise ValueError("Índice de elemento inválido; leia a janela novamente.")
    encontrados = [e for e in elementos if alvo in
                   (e.element_info.name, e.element_info.automation_id)]
    if len(encontrados) != 1:
        raise ValueError("Alvo ausente ou ambíguo; use o índice de ler_janela.")
    return encontrados[0]


def ler_janela(titulo, limite=4000):
    from pywinauto.uia_defines import NoPatternInterfaceError
    linhas = []
    for indice, elemento in enumerate(_elementos(_janela(titulo))):
        info = elemento.element_info
        valor = ""
        if not info.element.CurrentIsPassword:
            try:
                valor = elemento.iface_value.CurrentValue
            except NoPatternInterfaceError:
                pass
        linhas.append(json.dumps({"indice": indice, "tipo": info.control_type,
                                 "nome": info.name, "valor": valor,
                                 "automation_id": info.automation_id}, ensure_ascii=False))
    return "\n".join(linhas)[:max(0, limite)]


def preencher_campo(titulo, alvo, texto):
    from pywinauto.uia_defines import NoPatternInterfaceError
    elemento = _resolver_alvo(_elementos(_janela(titulo)), alvo)
    try:
        elemento.iface_value.SetValue(texto)
    except NoPatternInterfaceError:
        return "O elemento não expõe ValuePattern de UI Automation; use as ferramentas físicas."
    return "Campo preenchido."


def acionar(titulo, alvo):
    from pywinauto.uia_defines import NoPatternInterfaceError
    elemento = _resolver_alvo(_elementos(_janela(titulo)), alvo)
    for interface, metodo in (("iface_invoke", "Invoke"), ("iface_toggle", "Toggle"),
                              ("iface_selection_item", "Select")):
        try:
            padrao = getattr(elemento, interface)
        except NoPatternInterfaceError:
            continue
        getattr(padrao, metodo)()
        return "Elemento acionado."
    return "O elemento não expõe Invoke, Toggle ou SelectionItem; use as ferramentas físicas."


def capturar_janela(titulo, caminho):
    import win32gui
    import win32ui
    import cv2
    import numpy as np

    hwnd = _janela(titulo).handle
    if win32gui.IsIconic(hwnd):
        raise RuntimeError("A janela está minimizada; precisa estar restaurada para capturar.")
    esquerda, topo, direita, baixo = win32gui.GetWindowRect(hwnd)
    largura, altura = direita - esquerda, baixo - topo
    if largura <= 0 or altura <= 0:
        raise RuntimeError("A janela não tem área para captura.")
    hdc = win32gui.GetWindowDC(hwnd)
    origem = destino = bitmap = anterior = None
    try:
        origem = win32ui.CreateDCFromHandle(hdc)
        destino = origem.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(origem, largura, altura)
        anterior = destino.SelectObject(bitmap)
        from ctypes import wintypes
        imprimir = ctypes.windll.user32.PrintWindow
        imprimir.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        imprimir.restype = wintypes.BOOL
        if not imprimir(hwnd, destino.GetSafeHdc(), 2):  # PW_RENDERFULLCONTENT
            raise RuntimeError("O aplicativo não permitiu a captura por PrintWindow.")
        # BGRX → BGR, que é o formato do OpenCV (já usado pelo sentidos).
        pixels = np.frombuffer(bitmap.GetBitmapBits(True), dtype=np.uint8)
        if not cv2.imwrite(str(caminho), pixels.reshape(altura, largura, 4)[:, :, :3]):
            raise RuntimeError("Não consegui salvar a captura.")
        return caminho
    finally:
        if anterior is not None:
            destino.SelectObject(anterior)
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        if destino is not None:
            destino.DeleteDC()
        if origem is not None:
            origem.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)
