"""Delegações com agentes falsos e banco temporário, sem acessar dispositivos."""

import importlib
import json
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def delegacao(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    modulo = importlib.import_module("delegacao")
    monkeypatch.setattr(modulo, "_trabalhos", {})
    monkeypatch.setattr(modulo.registro, "BANCO", tmp_path / "registro.db")
    monkeypatch.delenv("SECRETARIO_DELEGACAO", raising=False)
    return modulo


def aguardar(modulo, id):
    limite = time.monotonic() + 5
    while time.monotonic() < limite:
        with modulo._trava:
            if not modulo._trabalhos[id]["ativo"]:
                return modulo.estado(id)
        time.sleep(0.01)
    pytest.fail("A thread falsa não terminou.")


def test_estados_persistencia_e_ambiente(delegacao, monkeypatch, tmp_path):
    entrou, liberar = threading.Event(), threading.Event()

    def executar(agente, tarefa, evento, **opcoes):
        assert agente == "codex" and tarefa == "Trabalho completo"
        assert opcoes["pasta"] == str(tmp_path.resolve())
        assert opcoes["env"]["SECRETARIO_DELEGACAO"] == "1"
        evento({"tipo": "ferramenta", "nome": "comando"})
        entrou.set()
        assert liberar.wait(5)
        return {"resposta": "x" * 5000, "ferramentas": ["comando"]}

    monkeypatch.setattr(delegacao.motores_cli, "executar", executar)
    id = delegacao.iniciar("codex", "Trabalho completo", tmp_path)
    try:
        assert entrou.wait(5)
        assert delegacao.estado(id)["status"] == "rodando"
        assert delegacao.estado(id)["ferramentas"] == ["comando"]
    finally:
        liberar.set()
    resultado = aguardar(delegacao, id)
    assert resultado["status"] == "ok"
    assert len(resultado["resposta"]) == 4000
    assert resultado["inicio"] and resultado["fim"]
    assert "SECRETARIO_DELEGACAO" not in delegacao.os.environ
    delegacao._trabalhos.clear()
    assert delegacao.estado(id) == resultado
    assert delegacao.listar() == [resultado]


def test_falha_e_validacao(delegacao, monkeypatch):
    def falhar(*args, **kwargs):
        raise RuntimeError("Falha do agente")

    monkeypatch.setattr(delegacao.motores_cli, "executar", falhar)
    id = delegacao.iniciar("claude", "Trabalho")
    assert aguardar(delegacao, id)["status"] == "erro"
    assert delegacao.estado(id)["resposta"] == "Falha do agente"
    with pytest.raises(ValueError):
        delegacao.iniciar("inexistente", "Trabalho")
    with pytest.raises(ValueError):
        delegacao.iniciar("claude", " ")
    with pytest.raises(ValueError):
        delegacao.estado("inexistente")


def test_limite_e_cancelamento(delegacao, monkeypatch):
    liberar = threading.Event()
    processos = []

    def executar(agente, tarefa, evento, **opcoes):
        proc = object()
        processos.append(proc)
        evento({"tipo": "processo", "proc": proc})
        assert liberar.wait(5)
        return {"resposta": "Terminou", "ferramentas": []}

    mortos = []
    monkeypatch.setattr(delegacao.motores_cli, "executar", executar)
    monkeypatch.setattr(delegacao.motores_cli, "_matar_arvore", mortos.append)
    ids = []
    try:
        ids = [delegacao.iniciar("codex", "Trabalho") for _ in range(3)]
        with pytest.raises(ValueError, match="Máximo de 3"):
            delegacao.iniciar("claude", "Outro")
        assert delegacao.cancelar(ids[0])["status"] == "cancelada"
        with pytest.raises(ValueError, match="Máximo de 3"):
            delegacao.iniciar("claude", "Outro")
    finally:
        liberar.set()
        for id in ids:
            aguardar(delegacao, id)
    assert delegacao.estado(ids[0])["status"] == "cancelada"
    assert len(mortos) <= 1
    assert all(proc in processos for proc in mortos)


def test_cancelar_antes_do_callback(delegacao, monkeypatch):
    entrou, liberar = threading.Event(), threading.Event()
    proc = object()
    mortos = []

    def executar(agente, tarefa, evento, **opcoes):
        entrou.set()
        assert liberar.wait(5)
        evento({"tipo": "processo", "proc": proc})
        raise RuntimeError("Processo cancelado")

    monkeypatch.setattr(delegacao.motores_cli, "executar", executar)
    monkeypatch.setattr(delegacao.motores_cli, "_matar_arvore", mortos.append)
    id = delegacao.iniciar("claude", "Trabalho")
    try:
        assert entrou.wait(5)
        delegacao.cancelar(id)
    finally:
        liberar.set()
    assert aguardar(delegacao, id)["status"] == "cancelada"
    assert mortos == [proc]


@pytest.mark.parametrize("valor", ["1", ""])
def test_recusa_recursao(delegacao, monkeypatch, valor):
    monkeypatch.setenv("SECRETARIO_DELEGACAO", valor)
    with pytest.raises(ValueError, match="delegação aninhada não permitida"):
        delegacao.iniciar("claude", "Trabalho")
    assert delegacao.listar() == []


def test_comando_claude_e_resposta(delegacao):
    cli = delegacao.motores_cli
    base = ["claude", "-p", "Sistema\n\nPedido: Trabalho", "--output-format", "json",
            "--permission-mode", "auto"]
    assert cli.montar_comando("claude", "Trabalho", prompt_sistema="Sistema") == base
    assert cli.montar_comando("claude", "Trabalho", "abc", "Sistema") == base + ["--resume", "abc"]
    assert cli.interpretar_linha("claude", json.dumps({"result": "Feito", "session_id": "abc"})) == {
        "tipo": "resposta", "texto": "Feito", "sessao": "abc"}


@pytest.mark.parametrize("agente", ["claude", "codex", "gemini-cli", "qwen"])
def test_executor_pasta_ambiente_e_resolucao(delegacao, monkeypatch, tmp_path, agente):
    import io

    cli = delegacao.motores_cli
    saida = (json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": "Feito"}}) if agente == "codex"
        else json.dumps({"result" if agente == "claude" else "response": "Feito"}))

    class Processo:
        stdout = io.StringIO(saida)

        def poll(self):
            return 0

        def wait(self):
            return 0

    ambiente = dict(SECRETARIO_DELEGACAO="1")

    def abrir(comando, **opcoes):
        assert comando[:2] == ["node", "agente.js"]
        assert opcoes["cwd"] == str(tmp_path)
        assert opcoes["env"] == ambiente
        assert opcoes["stdin"] == cli.subprocess.DEVNULL
        if agente == "codex":
            assert comando[comando.index("-C") + 1] == str(tmp_path)
            assert "--skip-git-repo-check" in comando
        return Processo()

    monkeypatch.setattr(cli, "resolver_executavel", lambda nome: ["node", "agente.js"])
    monkeypatch.setattr(cli.subprocess, "Popen", abrir)
    assert cli.executar(agente, "Trabalho", lambda e: None, pasta=tmp_path,
                        env=ambiente)["resposta"] == "Feito"
