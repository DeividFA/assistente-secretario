"""Adaptadores CLI sem executar agentes reais."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def cli():
    caminho = Path(__file__).resolve().parents[1] / "motores_cli.py"
    spec = importlib.util.spec_from_file_location("motores_cli_t22", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_comando_codex(cli):
    base = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(Path.home())]
    assert cli.montar_comando("codex", "oi", prompt_sistema="Sistema") == (
        base + ["--json", "--", "Sistema\n\nPedido: oi"])
    assert cli.montar_comando("codex", "oi", "sessao") == (
        base + ["resume", "sessao", "--json", "--", "\n\nPedido: oi"])


@pytest.mark.parametrize("nome,executavel", [("qwen", "qwen"), ("gemini-cli", "gemini")])
def test_comando_outros(cli, nome, executavel):
    base = [executavel, "-p", "Sistema\n\nPedido: oi", "--output-format", "json"]
    assert cli.montar_comando(nome, "oi", prompt_sistema="Sistema") == base
    assert cli.montar_comando(nome, "oi", "abc", "Sistema") == base + ["--resume", "abc"]


def test_eventos_codex(cli):
    assert cli.interpretar_linha("codex", '{"type":"thread.started","thread_id":"abc"}') == {
        "tipo": "sessao", "sessao": "abc"}
    item = {"id": "item_1", "type": "command_execution", "command": "dir"}
    assert cli.interpretar_linha("codex", json.dumps({"type": "item.started", "item": item})) == {
        "tipo": "ferramenta", "nome": "command_execution", "id": "item_1", "comando": "dir"}
    assert cli.interpretar_linha("codex", json.dumps({"type": "item.completed", "item": item})) is None
    assert cli.interpretar_linha("codex", json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": "Feito"}})) == {"tipo": "resposta", "texto": "Feito"}


@pytest.mark.parametrize("nome,campo", [("gemini-cli", "response"), ("qwen", "response"),
                                         ("qwen", "result")])
def test_respostas_json(cli, nome, campo):
    assert cli.interpretar_linha(nome, json.dumps({campo: "Olá", "session_id": "abc"})) == {
        "tipo": "resposta", "texto": "Olá", "sessao": "abc"}


@pytest.mark.parametrize("linha", ["aviso", "{", "[]", "null", "42", '{"type":"turn.completed"}'])
def test_ignora_linhas(cli, linha):
    for nome in cli.EXECUTAVEIS:
        assert cli.interpretar_linha(nome, linha) is None


def test_motor_desconhecido(cli):
    with pytest.raises(ValueError):
        cli.montar_comando("inexistente", "oi")


def processo_falso(cli, monkeypatch, saida, codigo=0):
    class Processo:
        pid = 123
        stdout = io.StringIO(saida)

        def poll(self):
            return codigo

        def wait(self):
            return codigo

    proc = Processo()
    def abrir(comando, **opcoes):
        assert opcoes["stdin"] == cli.subprocess.DEVNULL
        assert opcoes["stdout"] == cli.subprocess.PIPE
        assert opcoes["cwd"] == str(Path.home())
        return proc
    monkeypatch.setattr(cli.subprocess, "Popen", abrir)
    monkeypatch.setattr(cli.shutil, "which", lambda nome: nome)
    return proc


def test_executar_codex(cli, monkeypatch):
    saida = '\n'.join(json.dumps(item) for item in [
        {"type": "thread.started", "thread_id": "abc"},
        {"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "abrir"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Antes"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Depois"}}])
    proc = processo_falso(cli, monkeypatch, saida)
    eventos = []
    resultado = cli.executar("codex", "oi", eventos.append)
    assert eventos[0] == {"tipo": "processo", "proc": proc}
    assert resultado == {"resposta": "Depois", "sessao": "abc", "ferramentas": ["abrir"], "proc": proc}
    assert proc.stdout.closed


@pytest.mark.parametrize("nome", ["qwen", "gemini-cli"])
def test_executar_json_indentado(cli, monkeypatch, nome):
    processo_falso(cli, monkeypatch, json.dumps({"response": "Feito", "session_id": "abc"}, indent=2))
    assert cli.executar(nome, "oi", lambda evento: None)["resposta"] == "Feito"


def test_erro_processo(cli, monkeypatch):
    processo_falso(cli, monkeypatch, "", codigo=1)
    with pytest.raises(RuntimeError, match="código 1"):
        cli.executar("codex", "oi", lambda evento: None)


def test_qwen_lista_de_eventos(cli, monkeypatch):
    processo_falso(cli, monkeypatch, json.dumps([
        {"type": "system", "subtype": "init", "session_id": "abc"},
        {"type": "result", "result": "Feito", "session_id": "abc"}]))
    eventos = []
    resultado = cli.executar("qwen", "oi", eventos.append)
    assert resultado["sessao"] == "abc"
    assert resultado["resposta"] == "Feito"
    assert [evento["tipo"] for evento in eventos] == ["processo", "sessao", "resposta"]


@pytest.mark.parametrize("saida", ["inválido", '{"error":{"message":"falhou"}}'])
def test_resposta_invalida(cli, monkeypatch, saida):
    processo_falso(cli, monkeypatch, saida)
    with pytest.raises(RuntimeError):
        cli.executar("gemini-cli", "oi", lambda evento: None)


def test_callback_falha_mata_arvore(cli, monkeypatch):
    proc = processo_falso(cli, monkeypatch, "")
    monkeypatch.setattr(proc, "poll", lambda: None)
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cli.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    chamadas = []
    monkeypatch.setattr(cli.subprocess, "run", lambda comando, **opcoes: chamadas.append(comando))

    def falhar(evento):
        raise RuntimeError("callback falhou")

    with pytest.raises(RuntimeError, match="callback falhou"):
        cli.executar("codex", "oi", falhar)
    assert chamadas == [["taskkill", "/pid", "123", "/T", "/F"]]
    assert proc.stdout.closed
