import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comum
import vocabulario
from assistente_voz import ATIVACAO, ativacao_tolerante


@pytest.fixture
def correcoes(tmp_path, monkeypatch):
    caminho = tmp_path / "correcoes.json"
    monkeypatch.setattr(vocabulario, "CORRECOES", caminho)
    return caminho


def test_correcoes_iniciais_e_fronteiras(correcoes):
    assert vocabulario.corrigir("DAVID usa CLOUD e gloco de notas") == "Deivid usa Claude e bloco de notas"
    assert vocabulario.corrigir("Davidson cloudflare") == "Davidson cloudflare"
    # as correções padrão valem sempre, sem precisar estar gravadas no arquivo do usuário
    assert json.loads(correcoes.read_text(encoding="utf-8")) == {}


def test_preserva_correcoes_existentes(correcoes):
    correcoes.write_text('{"teste": "certo", "David": "David"}', encoding="utf-8")
    # as do usuário somam-se às padrão e têm prioridade sobre elas
    assert vocabulario.corrigir("David teste linketim") == "David certo LinkedIn"
    assert json.loads(correcoes.read_text(encoding="utf-8")) == {"teste": "certo", "David": "David"}


def test_aprender_correcao_normaliza_sem_duplicar(correcoes):
    vocabulario.aprender_correcao("  CLÓUD! ", "Claude")
    vocabulario.aprender_correcao("cloud", "Claude Code")
    pares = json.loads(correcoes.read_text(encoding="utf-8"))
    assert pares["cloud"] == "Claude Code"
    assert len([k for k in pares if comum.normalizar(k) == "cloud"]) == 1
    assert vocabulario.corrigir("Cloud") == "Claude Code"


@pytest.mark.parametrize("texto", [
    "Secretário, abre", "secretaria abre", "se cretário, abre",
    "secretárie: abre", "oi secretaro abre", "oi se cretário abre",
])
def test_ativacao_tolerante(texto):
    achou = ATIVACAO.search(texto) or ativacao_tolerante(texto)
    assert achou is not None
    assert texto[achou.end():] == "abre"


@pytest.mark.parametrize("texto", [
    "secretariado", "secretariado abre", "subsecretario abre",
    "abre o navegador", "quero chamar secretarie", "",
])
def test_rejeita_ativacao(texto):
    assert ATIVACAO.search(texto) is None
    assert ativacao_tolerante(texto) is None


def test_termos_indice_e_ordem(tmp_path):
    (tmp_path / ".secretario").mkdir()
    antiga = tmp_path / "Antiga.md"
    nova = tmp_path / "Nova.md"
    antiga.touch()
    nova.touch()
    os.utime(antiga, (100, 100))
    os.utime(nova, (200, 200))
    notas = [
        {"caminho": "Antiga.md", "titulo": "Antiga", "aliases": ["Outro"]},
        {"caminho": "Nova.md", "titulo": "Nova", "aliases": ["Novidade", "deivid"]},
    ]
    (tmp_path / ".secretario" / "indice.json").write_text(
        json.dumps({"notas": notas}), encoding="utf-8")
    resultado = vocabulario.termos(tmp_path)
    assert resultado == vocabulario.FIXOS + ["Nova", "Novidade", "Antiga", "Outro"]
    assert len(vocabulario.termos(tmp_path, limite=3)) == 3
    assert vocabulario.termos(tmp_path, limite=0) == []


def test_termos_sem_indice(tmp_path):
    assert vocabulario.termos(tmp_path) == vocabulario.FIXOS


def test_transcrever_vad_vocabulario_cache_e_correcao(monkeypatch, correcoes):
    chamadas, argumentos = [], []

    def termos():
        chamadas.append(True)
        return ["Deivid", "Secretário"]

    def transcrever(audio, **opcoes):
        argumentos.append(opcoes)
        return iter([SimpleNamespace(text="David abre")]), None

    relogio = [10]
    monkeypatch.setattr(comum, "_modelo", SimpleNamespace(transcribe=transcrever))
    monkeypatch.setattr(comum, "_termos", None)
    monkeypatch.setattr(comum, "_termos_ate", 0)
    monkeypatch.setattr(comum.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(vocabulario, "termos", termos)
    assert comum.transcrever(None) == "Deivid abre"
    relogio[0] = 309
    comum.transcrever(None)
    assert len(chamadas) == 1
    relogio[0] = 310
    comum.transcrever(None)
    assert len(chamadas) == 2
    assert argumentos[0]["hotwords"] == "Deivid Secretário"
    assert "Deivid" in argumentos[0]["initial_prompt"]
    assert argumentos[0]["vad_filter"] is True
    assert argumentos[0]["vad_parameters"] == {"min_silence_duration_ms": 500}
