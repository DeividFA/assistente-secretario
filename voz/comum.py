"""Peças compartilhadas pelo servidor MCP e pelo assistente de voz:
microfone com detecção de fala, transcrição e fala (voz do Windows)."""

import io
import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
import wave
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
    """Microfone compartilhado; gravar_fala() devolve o trecho entre o início
    da fala e a próxima pausa."""

    def __init__(self, dispositivo=None, abrir=True):
        dispositivo = dispositivo if dispositivo is not None else os.environ.get(
            "SECRETARIO_MIC", config.carregar()["microfone"])
        if isinstance(dispositivo, str) and dispositivo.isdigit():
            dispositivo = int(dispositivo)
        self.fila = queue.Queue()
        self.nivel = 0.0
        self.mudo = False      # enquanto o secretário fala
        self.pausado = False   # microfone mutado pelo usuário
        self.dispositivo = dispositivo
        self.preferido = dispositivo
        self.stream = None
        self.limiar = 0.01
        self.erro = ""
        self.tentar_apos = 0.0
        self.trava = threading.RLock()
        self.calibrando = False
        self.ultimo_audio = 0.0
        if abrir:
            self.retomar()

    def liberar(self):
        with self.trava:
            stream, self.stream = self.stream, None
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass
            self.nivel = 0.0
            self.limpar()

    @property
    def pausado(self):
        return self._pausado

    @pausado.setter
    def pausado(self, valor):
        self._pausado = bool(valor)
        if self._pausado:
            self.liberar()

    def retomar(self):
        with self.trava:
            if self.pausado:
                return False
            if self.disponivel():
                return True
            if time.monotonic() < self.tentar_apos:
                return False
            # Stream caiu: recomeça pelo microfone escolhido (o fone pode ter voltado);
            # o padrão do Windows só entra quando ele falha.
            if self.stream is not None:
                self.dispositivo = self.preferido
            self.liberar()
            try:
                dispositivo = sd.query_devices(self.dispositivo, "input")
                api = sd.query_hostapis(dispositivo["hostapi"])["name"]
                extra = sd.WasapiSettings(exclusive=False) if "WASAPI" in api.upper() else None
                self.erro = ""
                self.stream = sd.InputStream(samplerate=TAXA, channels=1, dtype="float32",
                                             blocksize=BLOCO, device=self.dispositivo,
                                             callback=self._cb, extra_settings=extra)
                self.calibrando = True
                self.ultimo_audio = time.monotonic()
                self.stream.start()
                self.limiar = self._calibrar()
                if self.erro:
                    raise RuntimeError(self.erro)
                return True
            except Exception as erro:
                self.erro = str(erro) or type(erro).__name__
                self.liberar()
                # Alterna entre o escolhido e o padrão a cada tentativa.
                self.dispositivo = None if self.dispositivo == self.preferido else self.preferido
                self.tentar_apos = time.monotonic() + 2
                return False
            finally:
                self.calibrando = False

    def disponivel(self):
        stream = self.stream
        if stream is None or self.erro:
            return False
        try:
            return stream.active and time.monotonic() - self.ultimo_audio < 2
        except Exception as erro:
            self.erro = str(erro)
            return False

    def _cb(self, dados, frames, t, status):
        # status (ex.: input overflow com a CPU ocupada pelo Whisper) é passageiro e não
        # derruba o stream; queda de verdade aparece como falta de áudio em disponivel().
        self.ultimo_audio = time.monotonic()
        self.nivel = rms(dados[:, 0])
        if self.calibrando or not (self.mudo or self.pausado):
            self.fila.put(dados[:, 0].copy())

    def limpar(self):
        while True:
            try:
                self.fila.get_nowait()
            except queue.Empty:
                return

    def _calibrar(self, segundos=1.0):
        blocos = [self.fila.get(timeout=0.3) for _ in range(int(segundos * TAXA / BLOCO))]
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
            if self.pausado or not self.disponivel():
                return None
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
        self.liberar()


_modelo = None
_termos = None
_termos_ate = 0


def transcrever(audio):
    """Transcreve áudio 16 kHz mono (float32), com fallback para Whisper local."""
    global _modelo, _termos, _termos_ate
    configuracao = config.carregar()
    agora = time.monotonic()
    if _termos is None or agora >= _termos_ate:
        _termos = vocabulario.termos()
        _termos_ate = agora + 300
    texto = None
    provedor = configuracao.get("transcricao", "local")
    if provedor in ("groq", "openai"):
        try:
            import provedores
            with io.BytesIO() as memoria:
                with wave.open(memoria, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(TAXA)
                    amostras = (np.clip(audio, -1, 1) * 32767).astype("<i2")
                    wav.writeframes(amostras.tobytes())
                texto = provedores.transcrever_audio(provedor, memoria.getvalue(), _termos)
        except Exception:
            # Sem chave, rede ou resposta válida: usa o áudio original localmente.
            texto = None
    if texto is None:
        if _modelo is None:
            from faster_whisper import WhisperModel
            nome = os.environ.get("SECRETARIO_WHISPER", configuracao["modelo_whisper"])
            _modelo = WhisperModel(nome, device="cpu", compute_type="int8")
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


_processo_fala = None
_trava_fala = threading.Lock()


class Fala:
    """Representa uma fala, sem confundir seu fim com o fim do processo."""

    def __init__(self, proc):
        self.proc = proc
        self.pronto = threading.Event()
        self.codigo = None

    def kill(self):
        if not self.pronto.is_set() and self.proc.poll() is None:
            self.proc.kill()

    def poll(self):
        if self.pronto.is_set():
            return self.codigo
        return self.proc.poll()

    def wait(self, timeout=None):
        if not self.pronto.wait(timeout):
            raise subprocess.TimeoutExpired("fala", timeout)
        return self.poll()


def interromper_fala():
    if _processo_fala is not None and _processo_fala.poll() is None:
        _processo_fala.kill()


atexit.register(interromper_fala)


def aquecer_voz():
    """Carrega o modelo Piper escolhido antes da primeira fala (~6 s a menos nela)."""
    voz = config.carregar().get("voz", "windows")
    if voz.startswith("piper:"):
        falar("", esperar=False, voz=voz, aquecer=True)


def falar(texto, esperar=True, voz=None, aquecer=False):
    """Reutiliza o processo; o retorno ainda permite kill, wait e poll."""
    global _processo_fala
    # A trava fica com o leitor até o fim, inclusive em chamadas sem espera.
    _trava_fala.acquire()
    try:
        if _processo_fala is None or _processo_fala.poll() is not None:
            if _processo_fala is not None:
                _processo_fala.stdin.close()
                _processo_fala.stdout.close()
            _processo_fala = subprocess.Popen(
                [sys.executable, str(BASE / "falar_proc.py")], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, text=True, encoding="utf-8",
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                creationflags=subprocess.CREATE_NO_WINDOW)
        proc = _processo_fala
        configuracao = config.carregar()
        pedido = {"texto": texto, "voz": voz or configuracao.get("voz", "windows"),
                  "velocidade": os.environ.get("SECRETARIO_VELOCIDADE_FALA",
                                               configuracao["velocidade_fala"])}
        if aquecer:
            pedido = {"carregar": pedido["voz"]}
        retorno = Fala(proc)
        proc.stdin.write(json.dumps(pedido, ensure_ascii=False) + "\n")
        proc.stdin.flush()
    except Exception:
        interromper_fala()
        _trava_fala.release()
        raise

    def aguardar():
        try:
            for linha in proc.stdout:
                try:
                    terminou = json.loads(linha).get("fim")
                except (ValueError, AttributeError):
                    continue
                if terminou:
                    break
            else:
                proc.wait()
                proc.stdin.close()
                proc.stdout.close()
        finally:
            retorno.codigo = proc.poll() if proc.poll() is not None else 0
            retorno.pronto.set()
            _trava_fala.release()

    threading.Thread(target=aguardar, daemon=True).start()
    if esperar:
        retorno.wait()
    return retorno


def texto_para_fala(texto, limite=700):
    """Tira markdown e encurta respostas longas antes de falar."""
    t = re.sub(r"```.*?```", " ", texto, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "link", t)
    t = t.replace("~~", "")
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
