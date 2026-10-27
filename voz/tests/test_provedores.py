"""Provedores com rede e keyring falsos, sem acessar credenciais reais."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest


@pytest.fixture
def provedores(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    caminho = Path(__file__).resolve().parents[1] / "provedores.py"
    spec = importlib.util.spec_from_file_location("provedores_t21", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "keyring", SimpleNamespace(
        get_password=lambda *args: None, set_password=lambda *args: None))
    for variavel in modulo.VARIAVEIS_CHAVES.values():
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setattr(modulo.config, "carregar", lambda: {})

    def sem_rede(*args, **kwargs):
        raise OSError("Rede desativada no teste")

    monkeypatch.setattr(modulo.urllib.request, "urlopen", sem_rede)
    return modulo


class Resposta:
    def __init__(self, dados):
        self.dados = dados

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.dados).encode("utf-8")


def test_chaves_e_prioridade(provedores, monkeypatch):
    salvas = {}
    monkeypatch.setattr(provedores.keyring, "set_password",
                        lambda servico, nome, valor: salvas.update({(servico, nome): valor}))
    monkeypatch.setattr(provedores.keyring, "get_password",
                        lambda servico, nome: salvas.get((servico, nome)))
    monkeypatch.setenv("XAI_API_KEY", "ambiente")
    assert provedores.ler_chave("grok") == "ambiente"
    provedores.salvar_chave("grok", "cofre")
    assert salvas == {("secretario", "grok"): "cofre"}
    assert provedores.ler_chave("grok") == "cofre"


def test_listar(provedores, monkeypatch):
    monkeypatch.setattr(provedores.shutil, "which", lambda nome: "caminho" if nome == "codex" else None)
    monkeypatch.setattr(provedores.keyring, "get_password",
                        lambda servico, nome: "segredo" if nome == "gpt" else None)
    lista = {item["nome"]: item for item in provedores.listar()}
    assert set(lista) == set(provedores.MOTORES)
    assert lista["codex"]["disponivel"]
    assert lista["gpt"]["disponivel"]
    for nome in ("claude", "grok", "gemma"):
        assert not lista[nome]["disponivel"]
        assert lista[nome]["motivo"]
    assert "segredo" not in str(lista)
    assert set(lista["gpt"]) == {"nome", "rotulo", "tipo", "disponivel", "motivo"}


def test_ollama(provedores, monkeypatch):
    def abrir(url, timeout):
        assert url == "http://localhost:11434/api/tags"
        assert timeout == 2
        return Resposta({"models": []})

    monkeypatch.setattr(provedores.urllib.request, "urlopen", abrir)
    assert provedores.disponivel("gemma") == (True, "")


def test_chamar_api(provedores, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "segredo")
    monkeypatch.setattr(provedores.config, "carregar", lambda: {"modelos": {"grok": "outro"}})
    mensagens = [{"role": "user", "content": "Veja"}, {"role": "assistant", "content": "Certo"}]

    def abrir(pedido, timeout):
        assert pedido.full_url == "https://api.x.ai/v1/chat/completions"
        assert pedido.get_method() == "POST"
        assert pedido.get_header("Authorization") == "Bearer segredo"
        assert pedido.get_header("Content-type") == "application/json"
        assert timeout == 17
        dados = json.loads(pedido.data)
        assert dados["model"] == "outro"
        assert dados["temperature"] == 0.2
        assert dados["response_format"] == {"type": "json_object"}
        assert dados["messages"][0]["content"] == [
            {"type": "text", "text": "Veja"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,YWJj"}}]
        assert dados["messages"][1] == mensagens[1]
        return Resposta({"choices": [{"message": {"content": "resposta"}}]})

    monkeypatch.setattr(provedores.urllib.request, "urlopen", abrir)
    assert provedores.chamar_api("grok", mensagens, json=True, imagens=["YWJj"], timeout=17) == "resposta"
    assert mensagens[0]["content"] == "Veja"


def test_api_sem_chave_e_modelo_padrao(provedores, monkeypatch):
    def abrir(pedido, timeout):
        assert pedido.get_header("Authorization") is None
        dados = json.loads(pedido.data)
        assert dados["model"] == "gemma3:4b"
        assert "response_format" not in dados
        assert timeout == 120
        return Resposta({"choices": [{"message": {"content": "olá"}}]})

    monkeypatch.setattr(provedores.urllib.request, "urlopen", abrir)
    assert provedores.chamar_api("gemma", []) == "olá"


@pytest.mark.parametrize("http", [True, False])
def test_erro_nao_expoe_chave(provedores, monkeypatch, http):
    segredo = "chave-super-secreta"
    monkeypatch.setenv("OPENAI_API_KEY", segredo)

    def abrir(pedido, timeout):
        if http:
            raise urllib.error.HTTPError(pedido.full_url, 401, segredo, {}, io.BytesIO(segredo.encode()))
        raise OSError(segredo)

    monkeypatch.setattr(provedores.urllib.request, "urlopen", abrir)
    with pytest.raises(RuntimeError) as erro:
        provedores.chamar_api("gpt", [])
    assert segredo not in str(erro.value)
    assert erro.value.__suppress_context__
    if http:
        assert "401" in str(erro.value)


def test_keyring_falha_sem_expor_chave(provedores, monkeypatch):
    def falhar(*args):
        raise RuntimeError("segredo")

    monkeypatch.setattr(provedores.keyring, "set_password", falhar)
    monkeypatch.setattr(provedores.keyring, "get_password", falhar)
    monkeypatch.setenv("OPENAI_API_KEY", "alternativa")
    assert provedores.ler_chave("gpt") == "alternativa"
    with pytest.raises(RuntimeError, match="keyring") as erro:
        provedores.salvar_chave("gpt", "segredo")
    assert "segredo" not in str(erro.value)


def test_openrouter_exige_modelo_e_api_exige_chave(provedores, monkeypatch):
    with pytest.raises(RuntimeError, match="Chave"):
        provedores.chamar_api("gpt", [])
    monkeypatch.setenv("OPENROUTER_API_KEY", "segredo")
    with pytest.raises(RuntimeError, match="modelo"):
        provedores.chamar_api("openrouter", [])
