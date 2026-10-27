"""Microfone e registro com dispositivos, relógio e aplicativos falsos."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispositivos
import comum
import assistente_voz as motor


class Chave:
    def __init__(self, caminho):
        self.caminho = caminho

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_apps_registro(monkeypatch):
    base = r"C:\Python312\python.exe"
    monkeypatch.setattr(sys, "_base_executable", base, raising=False)
    raiz = dispositivos.CHAVE
    filhos = {
        raiz: ["NonPackaged", "AplicativoEmpacotado"],
        raiz + r"\NonPackaged": [base.replace("\\", "#").upper(),
                                  r"C:#app#electron.exe", r"C:#app#Discord.exe",
                                  r"C:#app#chrome.exe", r"C:#app#zoom.exe"],
    }
    valores = {
        "AplicativoEmpacotado": (10, 0), "C:#app#Discord.exe": (10, 0),
        "C:#app#chrome.exe": (10, 12), "C:#app#zoom.exe": (0, 0),
        base.replace("\\", "#").upper(): (10, 0), "C:#app#electron.exe": (10, 0),
    }

    def enumerar(chave, indice):
        try:
            return filhos.get(chave.caminho, [])[indice]
        except IndexError:
            raise OSError()

    def valor(chave, nome):
        dados = valores.get(chave.caminho.rsplit("\\", 1)[-1])
        if dados is None:
            raise OSError()
        return (dados[0 if nome == "LastUsedTimeStart" else 1], 0)

    monkeypatch.setattr(dispositivos, "winreg", SimpleNamespace(
        HKEY_CURRENT_USER=1, OpenKey=lambda _, caminho: Chave(caminho),
        EnumKey=enumerar, QueryValueEx=valor))
    assert dispositivos.apps_usando_microfone() == ["AplicativoEmpacotado", "Discord"]


def test_registro_indisponivel(monkeypatch):
    def negado(*args):
        raise OSError()
    monkeypatch.setattr(dispositivos, "winreg", SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=negado))
    assert dispositivos.apps_usando_microfone() == []


@pytest.fixture
def audio_falso(monkeypatch):
    streams = []
    dispositivos_abertos = []
    relogio = [100.0]

    class Stream:
        def __init__(self, **args):
            self.args = args
            self.active = False
            self.fechado = False
            streams.append(self)

        def start(self):
            self.active = True

        def stop(self):
            self.active = False

        def close(self):
            self.fechado = True

    def consultar(dispositivo, tipo):
        dispositivos_abertos.append(dispositivo)
        return {"hostapi": 0}

    monkeypatch.setattr(comum.sd, "InputStream", Stream)
    monkeypatch.setattr(comum.sd, "query_devices", consultar)
    monkeypatch.setattr(comum.sd, "query_hostapis", lambda _: {"name": "Windows WASAPI"})
    monkeypatch.setattr(comum.sd, "WasapiSettings", lambda **args: args)
    monkeypatch.setattr(comum.Microfone, "_calibrar", lambda self: 0.02)
    monkeypatch.setattr(comum.time, "monotonic", lambda: relogio[0])
    return streams, dispositivos_abertos, relogio


def test_liberar_retomar_pausa(audio_falso):
    streams, _, _ = audio_falso
    mic = comum.Microfone(3)
    assert streams[0].args["extra_settings"] == {"exclusive": False}
    mic.fila.put("audio antigo")
    mic.pausado = True
    assert streams[0].fechado and mic.stream is None and mic.fila.empty()
    assert not mic.retomar()
    mic.pausado = False
    assert mic.retomar() and mic.limiar == 0.02
    mic.liberar()
    mic.liberar()
    assert streams[-1].fechado


def test_recuperar_stream(audio_falso, monkeypatch):
    streams, abertos, relogio = audio_falso
    mic = comum.Microfone(3)
    streams[0].active = False
    assert mic.gravar_fala() is None
    assert mic.retomar()
    # Depois de uma queda, volta primeiro para o microfone escolhido.
    assert abertos == [3, 3] and streams[0].fechado
    mic.erro = "dispositivo removido"
    criar = comum.sd.InputStream

    def falhar(**args):
        raise OSError("sem dispositivo")

    monkeypatch.setattr(comum.sd, "InputStream", falhar)
    assert not mic.retomar()
    quantidade = len(abertos)
    assert not mic.retomar() and len(abertos) == quantidade
    relogio[0] += 2
    monkeypatch.setattr(comum.sd, "InputStream", criar)
    assert mic.retomar() and mic.dispositivo is None


@pytest.fixture
def assistente(audio_falso, monkeypatch):
    eventos = []
    monkeypatch.setattr(motor, "emitir", lambda **evento: eventos.append(evento))
    monkeypatch.setattr(motor, "interromper_fala", lambda: None)
    monkeypatch.setattr(dispositivos, "apps_usando_microfone", lambda: [])
    a = motor.Assistente()
    a.config_mic.update(modo_microfone="continuo", mic_em_chamada="liberar")
    return a, eventos


def test_maquina_microfone(assistente, audio_falso, monkeypatch):
    a, eventos = assistente
    _, _, relogio = audio_falso
    a.atualizar_microfone()
    assert a.mic.stream is not None
    monkeypatch.setattr(dispositivos, "apps_usando_microfone", lambda: ["Discord"])
    relogio[0] += 3
    a.atualizar_microfone()
    assert a.mic.stream is None
    assert any(e.get("app") == "Discord" and e.get("estado") == "liberado" for e in eventos)
    a.comando_mic_ate = relogio[0] + 15
    a.atualizar_microfone()
    assert a.mic.stream is not None
    a.comando_mic_ate = 0
    a.atualizar_microfone()
    assert a.mic.stream is None
    a.config_mic["mic_em_chamada"] = "compartilhar"
    a.atualizar_microfone()
    assert a.mic.stream is not None
    monkeypatch.setattr(dispositivos, "apps_usando_microfone", lambda: [])
    relogio[0] += 3
    a.atualizar_microfone()
    assert a.mic.stream is not None
    a.config_mic.update(mic_em_chamada="liberar", modo_microfone="sob_demanda")
    a.atualizar_microfone()
    assert a.mic.stream is None
    a.demanda_ativa = True
    a.comando_mic_ate = a.conversa_ate = relogio[0] + 15
    a.atualizar_microfone()
    assert a.mic.stream is not None
    relogio[0] += 16
    a.atualizar_microfone()
    assert a.mic.stream is None


def test_erro_callback_e_sem_audio(audio_falso):
    import numpy as np
    streams, _, relogio = audio_falso
    mic = comum.Microfone(3)
    # Aviso passageiro do PortAudio (ex.: input overflow) não derruba o stream.
    mic._cb(np.zeros((480, 1)), 480, None, "input overflow")
    assert mic.disponivel() and mic.retomar() and not streams[0].fechado
    # Sem áudio por 2 s = queda de verdade: reabre.
    relogio[0] += 3
    assert not mic.disponivel()
    assert mic.gravar_fala() is None
    assert mic.retomar() and streams[0].fechado


def test_pausa_tem_prioridade(assistente, audio_falso):
    a, eventos = assistente
    a.comando_mic_ate = audio_falso[2][0] + 15
    a.mic.pausado = True
    a.atualizar_microfone()
    assert a.mic.stream is None
    assert any(e.get("estado") == "mudo" for e in eventos)


def test_resposta_em_chamada_pela_fila(assistente, monkeypatch):
    a, eventos = assistente
    monkeypatch.setattr(dispositivos, "apps_usando_microfone", lambda: ["Discord"])
    def nao_falar(*args, **kwargs):
        pytest.fail("Não deve sintetizar durante chamada")
    monkeypatch.setattr(motor, "falar", nao_falar)
    a.dizer("Resposta na tela")
    original = a._dizer
    def terminar(*args):
        original(*args)
        a.ativo = False
    monkeypatch.setattr(a, "_dizer", terminar)
    a.falar_fila()
    assert {"evento": "resposta_silenciosa", "texto": "Resposta na tela"} in eventos
