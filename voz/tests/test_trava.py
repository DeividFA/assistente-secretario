import io
import json

import pytest

import trava

CLIQUE = "mcp__playwright__browser_click"


@pytest.fixture
def arquivo(tmp_path):
    return tmp_path / "aprovacao.json"


@pytest.mark.parametrize("elemento", ["Botão Enviar inscrição", "Pagar com Pix", "Publicar",
                                      "Finalizar compra", "Excluir conta", "Submit application"])
def test_bloqueia_clique_sensivel_sem_sim(arquivo, elemento):
    assert trava.decidir(CLIQUE, {"element": elemento, "ref": "e1"}, arquivo=arquivo)


@pytest.mark.parametrize("elemento", ["Próximo", "Campo Nome", "Aceitar cookies", "Ver vagas"])
def test_libera_clique_comum(arquivo, elemento):
    assert trava.decidir(CLIQUE, {"element": elemento}, arquivo=arquivo) is None


def test_sim_do_deivid_libera_uma_acao(arquivo):
    assert trava.registrar_fala("Sim, pode enviar.", agora=1000, arquivo=arquivo)
    entrada = {"element": "Botão Enviar"}
    assert trava.decidir(CLIQUE, entrada, agora=1010, arquivo=arquivo) is None
    assert trava.decidir(CLIQUE, entrada, agora=1020, arquivo=arquivo)  # o sim foi gasto


def test_sim_expira(arquivo):
    trava.registrar_fala("pode publicar", agora=1000, arquivo=arquivo)
    assert trava.decidir(CLIQUE, {"element": "Publicar"}, agora=1000 + trava.VALIDADE + 1,
                         arquivo=arquivo)


def test_pedido_comum_nao_aprova(arquivo):
    assert not trava.registrar_fala("abre o meu LinkedIn", arquivo=arquivo)
    assert not trava.registrar_fala("simplesmente pesquisa isso", arquivo=arquivo)
    assert not arquivo.exists()


def test_codigo_na_pagina_que_clica_precisa_de_sim(arquivo):
    ferramenta = "mcp__playwright__browser_run_code_unsafe"
    for codigo in ("async (page) => { await page.getByRole('button').click(); }",
                   "() => document.forms[0].requestSubmit()",
                   "async (page) => page.keyboard.press('Enter')"):
        assert trava.decidir(ferramenta, {"code": codigo}, arquivo=arquivo)
    assert trava.decidir("mcp__chrome__browser_evaluate",
                         {"function": "() => document.title"}, arquivo=arquivo) is None


def test_dialogo_aceito_precisa_de_sim(arquivo):
    ferramenta = "mcp__chrome__browser_handle_dialog"
    assert trava.decidir(ferramenta, {"accept": True}, arquivo=arquivo)
    assert trava.decidir(ferramenta, {"accept": False}, arquivo=arquivo) is None


def test_acionar_botao_de_programa(arquivo):
    assert trava.decidir("mcp__sentidos__acionar", {"titulo": "App", "alvo": "Excluir"},
                         arquivo=arquivo)


@pytest.mark.parametrize("url", ["https://www.itau.com.br/", "nubank.com.br/entrar",
                                 "https://app.mercadopago.com.br/x"])
def test_bancos_sempre_bloqueados(arquivo, url):
    trava.registrar_fala("sim", arquivo=arquivo)
    assert trava.decidir("mcp__playwright__browser_navigate", {"url": url}, arquivo=arquivo)


def test_site_comum_liberado(arquivo):
    assert trava.decidir("mcp__chrome__browser_navigate",
                         {"url": "https://www.linkedin.com/feed/"}, arquivo=arquivo) is None
    assert trava.decidir("mcp__sentidos__abrir", {"alvo": "notepad"}, arquivo=arquivo) is None


def test_secretario_nao_forja_aprovacao(arquivo):
    assert trava.decidir("Write", {"file_path": "C:/x/voz/sinais/aprovacao.json",
                                   "content": "{}"}, arquivo=arquivo)
    assert trava.decidir("Bash", {"command": "echo {} > sinais/APROVACAO.json"}, arquivo=arquivo)
    assert trava.decidir("Bash", {"command": "ls"}, arquivo=arquivo) is None


def test_hook_bloqueia_com_codigo_2(monkeypatch, arquivo):
    monkeypatch.setattr(trava, "APROVACAO", arquivo)
    monkeypatch.setattr(trava.decidir, "__defaults__", (None, arquivo))
    evento = io.StringIO(json.dumps({"tool_name": CLIQUE, "tool_input": {"element": "Enviar"}}))
    erro = io.StringIO()
    monkeypatch.setitem(__import__("sys").modules, "registro", None)
    assert trava.principal(evento, erro) == 2
    assert "trava de segurança" in erro.getvalue()
    assert trava.principal(io.StringIO("{}"), io.StringIO()) == 0


def test_configuracao_do_hook():
    config = json.loads(trava.configuracao_hook(python="C:\\venv\\python.exe"))
    hook = config["hooks"]["PreToolUse"][0]
    assert "mcp__playwright__" in hook["matcher"]
    assert hook["hooks"][0]["command"].startswith('"C:/venv/python.exe" "')
    assert hook["hooks"][0]["command"].endswith('trava.py"')
