"""Peças compartilhadas pelo servidor MCP e pelo assistente de voz:
microfone com detecção de fala, transcrição local (Whisper) e fala (voz do Windows)."""

import os
import queue
import re
import subprocess
import sys
import time
import unicodedata
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd

import config
import vocabulario

BASE = Path(__file__).resolve().parent
CAPTURAS = BASE.parent / "capturas"
CAPTURAS.mkdir(exist_ok=True)

TAXA = 16000
BLOCO = 480  # 30 ms

# Frases que o Whisper "alucina" em silêncio/ruído.
ALUCINACOES = {
    "obrigado", "obrigada", "tchau", "legendas pela comunidade amara.org",
    "legenda adriana zanotto", "e ai", "...",
}


def rms(bloco):
    return float(np.sqrt(np.mean(bloco * bloco)))


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", sem_acento.lower()).strip()


class Microfone:
    """Microfone aberto continuamente; gravar_fala() devolve o trecho entre o início
    da fala e a próxima pausa."""

    def __init__(self, dispositivo=None):
        dispositivo = dispositivo if dispositivo is not None else os.environ.get(
            "SECRETARIO_MIC", config.carregar()["microfone"])
        if isinstance(dispositivo, str) and dispositivo.isdigit():
            dispositivo = int(dispositivo)
        self.fila = queue.Queue()
        self.nivel = 0.0
        self.mudo = False      # enquanto o secretário fala
        self.pausado = False   # microfone mutado pelo usuário
        self.stream = sd.InputStream(samplerate=TAXA, channels=1, dtype="float32",
                                     blocksize=BLOCO, device=dispositivo, callback=self._cb)
        self.stream.start()
        self.limiar = self._calibrar()

    def _cb(self, dados, frames, t, status):
        self.nivel = rms(dados[:, 0])
        if not (self.mudo or self.pausado):
            self.fila.put(dados[:, 0].copy())

    def limpar(self):
        while True:
            try:
                self.fila.get_nowait()
            except queue.Empty:
                return

    def _calibrar(self, segundos=1.0):
        blocos = [self.fila.get() for _ in range(int(segundos * TAXA / BLOCO))]
        ruido = float(np.median([rms(b) for b in blocos]))
        return max(0.01, ruido * 3.5)

    def gravar_fala(self, espera_max=None, duracao_max=30.0, pausa=None):
        """Espera alguém falar e devolve o áudio até uma pausa. None se ninguém falou
        dentro de espera_max segundos."""
        antes = deque(maxlen=10)  # guarda 300 ms antes do início da fala
        inicio = time.monotonic()
        falando = False
        audio = []
        blocos_voz = 0
        blocos_silencio = 0
        # 0,9 s cortava frases em que o Deivid pausa para pensar ("abra o meu... LinkedIn")
        pausa = pausa if pausa is not None else float(config.carregar().get("pausa_fala", 1.4))
        limite_silencio = int(pausa * TAXA / BLOCO)
        while True:
            try:
                bloco = self.fila.get(timeout=0.3)
            except queue.Empty:
                bloco = None
            if not falando:
                if espera_max and time.monotonic() - inicio > espera_max:
                    return None
                if bloco is None:
                    continue
                antes.append(bloco)
                if rms(bloco) > self.limiar:
                    blocos_voz += 1
                    if blocos_voz >= 3:
                        falando = True
                        audio = list(antes)
                else:
                    blocos_voz = 0
                continue
            if bloco is None:
                continue
            audio.append(bloco)
            blocos_silencio = blocos_silencio + 1 if rms(bloco) < self.limiar else 0
            if blocos_silencio >= limite_silencio or len(audio) * BLOCO / TAXA > duracao_max:
                return np.concatenate(audio)

    def fechar(self):
        self.stream.stop()
        self.stream.close()


_modelo = None
_termos = None
_termos_ate = 0


def transcrever(audio):
    """Transcreve áudio 16 kHz mono (float32) em português, localmente."""
    global _modelo, _termos, _termos_ate
    if _modelo is None:
        from faster_whisper import WhisperModel
        nome = os.environ.get("SECRETARIO_WHISPER", config.carregar()["modelo_whisper"])
        _modelo = WhisperModel(nome, device="cpu", compute_type="int8")
    agora = time.monotonic()
    if _termos is None or agora >= _termos_ate:
        _termos = vocabulario.termos()
        _termos_ate = agora + 300
    segmentos, _ = _modelo.transcribe(
        audio, language="pt", beam_size=1, condition_on_previous_text=False,
        hotwords=" ".join(_termos),
        initial_prompt="Vocabulário: " + ", ".join(_termos[:15]) + ".",
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
    )
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    if normalizar(texto) in {normalizar(a) for a in ALUCINACOES}:
        return ""
    return vocabulario.corrigir(texto)


_FALA = r"""
import sys, pyttsx3
texto = sys.stdin.read()
e = pyttsx3.init()
for v in e.getProperty("voices"):
    if "Portug" in v.name or "pt" in str(v.languages).lower():
        e.setProperty("voice", v.id)
        break
e.setProperty("rate", int(sys.argv[1]))
e.say(texto)
e.runAndWait()
"""


def falar(texto, esperar=True):
    """Fala o texto com a voz pt-BR do Windows. Roda em outro processo para poder ser
    interrompida (proc.kill())."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    velocidade = str(os.environ.get(
        "SECRETARIO_VELOCIDADE_FALA", config.carregar()["velocidade_fala"]))
    proc = subprocess.Popen([sys.executable, "-c", _FALA, velocidade], stdin=subprocess.PIPE,
                            env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    proc.stdin.write(texto.encode("utf-8"))
    proc.stdin.close()
    if esperar:
        proc.wait()
    return proc


def texto_para_fala(texto, limite=700):
    """Tira markdown e encurta respostas longas antes de falar."""
    t = re.sub(r"```.*?```", " ", texto, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "link", t)
    t = re.sub(r"[*_`#>|]", "", t)
    t = re.sub(r"^\s*-{3,}\s*$", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limite:
        corte = t.rfind(".", 0, limite)
        t = t[: corte + 1 if corte > 200 else limite] + " Os detalhes estão na tela."
    return t


def bip(frequencia=880, duracao=120):
    try:
        import winsound
        winsound.Beep(frequencia, duracao)
    except Exception:
        pass
