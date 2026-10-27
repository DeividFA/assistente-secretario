"""Extração com respostas falsas, sem Ollama nem acesso ao cofre."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def extrator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    caminho = Path(__file__).resolve().parents[1] / "extrator.py"
    spec = importlib.util.spec_from_file_location("extrator_t12", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_json_valido_e_prompt(extrator):
    esperado = {"conceitos": [{
        "nome": "Jesus Cristo", "assunto": "Religião", "resumo": "Figura central.",
        "aliases": ["Jesus"], "relacionados": ["Bíblia"], "fato": "",
    }], "fatos_usuario": ["Deivid estuda a Bíblia."]}

    def chamar(mensagens):
        prompt = mensagens[0]["content"]
        assert all(assunto in prompt for assunto in extrator.memoria.ASSUNTOS)
        assert "Exemplo de entrada" in prompt
        assert '"relacionados": ["Bíblia"]' in prompt
        assert json.loads(mensagens[1]["content"])["pergunta"] == "Quem é Jesus?"
        return json.dumps(esperado)

    assert extrator.extrair("Quem é Jesus?", "Figura central.", chamar) == esperado


@pytest.mark.parametrize("saida", ["inválido", "[]", "null", "{", "42"])
def test_json_invalido(extrator, saida):
    assert extrator.extrair("oi", "olá", lambda _: saida) == {
        "conceitos": [], "fatos_usuario": []}


def test_campos_faltando(extrator):
    assert extrator.extrair("oi", "olá", lambda _: "{}") == {
        "conceitos": [], "fatos_usuario": []}
    resultado = extrator.extrair("x", "y", lambda _: json.dumps({
        "conceitos": [{}, {"nome": " "}, {"nome": " Bíblia "}, None]}))
    assert resultado == {"conceitos": [{
        "nome": "Bíblia", "assunto": "Outros", "resumo": "", "aliases": [],
        "relacionados": [], "fato": ""}], "fatos_usuario": []}


def test_limites_e_tipos(extrator):
    item = {"nome": "N" * 200, "assunto": "inexistente", "resumo": "r" * 2000,
            "fato": "f" * 1000, "aliases": [None, " Jesus ", "Jesus", 7],
            "relacionados": "Bíblia"}
    resultado = extrator.extrair("x", "y", lambda _: json.dumps({
        "conceitos": [item] * 8, "fatos_usuario": [None, "f" * 600]}))
    assert len(resultado["conceitos"]) == 5
    conceito = resultado["conceitos"][0]
    assert len(conceito["nome"]) == 120
    assert len(conceito["resumo"]) == 1000
    assert len(conceito["fato"]) == 500
    assert conceito["assunto"] == "Outros"
    assert conceito["aliases"] == ["Jesus"]
    assert conceito["relacionados"] == []
    assert len(resultado["fatos_usuario"][0]) == 300


def test_falha_da_chamada(extrator):
    def chamar(_):
        raise OSError("Ollama fechado")

    assert extrator.extrair("x", "y", chamar) == {
        "conceitos": [], "fatos_usuario": []}


def test_requisicao_padrao(extrator, monkeypatch):
    class Resposta:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"message": {"content": "{}"}}).encode("utf-8")

    def abrir(pedido, timeout):
        assert pedido.full_url == "http://localhost:11434/api/chat"
        assert pedido.get_method() == "POST"
        assert timeout == 120
        dados = json.loads(pedido.data)
        assert dados["model"] == "gemma3:4b"
        assert dados["format"] == "json"
        assert dados["stream"] is False
        assert dados["keep_alive"] == "30m"
        assert dados["options"] == {"temperature": 0.1}
        assert len(dados["messages"]) == 2
        return Resposta()

    monkeypatch.setattr(extrator.urllib.request, "urlopen", abrir)
    assert extrator.extrair("oi", "olá") == {"conceitos": [], "fatos_usuario": []}
