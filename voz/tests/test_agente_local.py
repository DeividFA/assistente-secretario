import base64
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agente_local


def roteiro(*respostas):
    respostas = iter(respostas)
    chamadas = []

    def chamar(mensagens, imagens=None):
        chamadas.append((copy.deepcopy(mensagens), copy.deepcopy(imagens)))
        resposta = next(respostas)
        return json.dumps(resposta) if isinstance(resposta, dict) else resposta

    return chamar, chamadas


@pytest.fixture(autouse=True)
def impedir_efeitos_reais(monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("Não deve executar ações nem chamar Ollama de verdade.")
    monkeypatch.setattr(agente_local.acoes, "executar", proibido)
    monkeypatch.setattr(agente_local, "urlopen", proibido)


def test_responde_direto_com_contexto_sem_mutar_historico():
    chamar, chamadas = roteiro({"acao": "responder", "texto": "Olá, Deivid."})
    historico = [{"role": "user", "content": "Oi"}]
    assert agente_local.executar("Olá", historico, "Memória de teste", chamar) == {
        "texto": "Olá, Deivid.", "pendente": None, "passos": [],
    }
    mensagens = chamadas[0][0]
    assert "Memória de teste" in mensagens[0]["content"]
    assert agente_local.acoes.descrever_acoes() in mensagens[0]["content"]
    assert mensagens[1] == historico[0]
    assert historico == [{"role": "user", "content": "Oi"}]


def test_abre_e_depois_responde(monkeypatch):
    executadas = []

    def executar(nome, args, pedido):
        executadas.append((nome, args, pedido))
        return {"ok": True, "texto": "Aberto.", "imagem": None}

    monkeypatch.setattr(agente_local.acoes, "executar", executar)
    chamar, chamadas = roteiro(
        {"acao": "abrir", "args": {"alvo": "calc"}},
        {"acao": "responder", "texto": "Pronto."},
    )
    resultado = agente_local.executar("abra a calculadora", chamar=chamar)
    assert resultado == {"texto": "Pronto.", "pendente": None, "passos": ["abrir"]}
    assert executadas == [("abrir", {"alvo": "calc"}, "abra a calculadora")]
    assert chamadas[1][0][-1]["content"] == "Resultado de abrir: Aberto."


def test_comando_perigoso_so_executa_apos_confirmar(monkeypatch):
    args = {"powershell": "Remove-Item arquivo.txt"}
    chamar, _ = roteiro({"acao": "comando", "args": args})
    resultado = agente_local.executar("apague o arquivo", chamar=chamar)
    assert resultado["texto"].startswith("Posso ")
    assert resultado["texto"].endswith("?")
    assert resultado["passos"] == []
    assert resultado["pendente"] == {
        "acao": "comando", "args": args, "pedido": "apague o arquivo",
    }
    executadas = []

    def executar(*argumentos):
        executadas.append(argumentos)
        return {"ok": True, "texto": "Concluído.", "imagem": None}

    monkeypatch.setattr(agente_local.acoes, "executar", executar)
    assert agente_local.confirmar(resultado["pendente"]) == {
        "texto": "Concluído.", "pendente": None, "passos": ["comando"],
    }
    assert executadas == [("comando", args, "apague o arquivo")]


@pytest.mark.parametrize("invalido", ["não é JSON", "[]", '{"acao":"responder"}', '{"acao":"abrir","args":[]}'])
def test_json_invalido_repetido_desiste(invalido):
    chamar, chamadas = roteiro(invalido, invalido)
    resultado = agente_local.executar("oi", chamar=chamar)
    assert resultado == {"texto": agente_local.DESISTENCIA, "pendente": None, "passos": []}
    assert len(chamadas) == 2


def test_ver_tela_envia_imagem_na_proxima_chamada(monkeypatch, tmp_path):
    caminho = tmp_path / "tela.png"
    caminho.write_bytes(b"imagem simulada")
    monkeypatch.setattr(agente_local.acoes, "executar", lambda *args: {
        "ok": True, "texto": "Tela capturada.", "imagem": str(caminho),
    })
    chamar, chamadas = roteiro(
        {"acao": "ver_tela", "args": {}},
        {"acao": "responder", "texto": "Vejo a tela."},
    )
    assert agente_local.executar("veja a tela", chamar=chamar)["passos"] == ["ver_tela"]
    assert chamadas[0][1] is None
    assert chamadas[1][1] == [base64.b64encode(b"imagem simulada").decode("ascii")]
    assert chamadas[1][0][-1]["images"] == chamadas[1][1]


def test_limite_de_passos(monkeypatch):
    monkeypatch.setattr(agente_local.acoes, "executar", lambda *args: {
        "ok": False, "texto": "Falha simulada.", "imagem": None,
    })
    chamar, chamadas = roteiro(*[{"acao": "janelas", "args": {}}] * 3)
    resultado = agente_local.executar("liste janelas", chamar=chamar, max_passos=3)
    assert resultado["texto"] == agente_local.DESISTENCIA
    assert resultado["passos"] == ["janelas"] * 3
    assert len(chamadas) == 3


def test_json_valido_zera_contagem_de_invalidos(monkeypatch):
    monkeypatch.setattr(agente_local.acoes, "executar", lambda *args: {
        "ok": True, "texto": "Nenhuma janela.", "imagem": None,
    })
    chamar, _ = roteiro("inválido", {"acao": "janelas", "args": {}}, "inválido",
                         {"acao": "responder", "texto": "Pronto."})
    assert agente_local.executar("oi", chamar=chamar)["texto"] == "Pronto."


def test_excecoes_nao_escapam(monkeypatch):
    def falhar(*args, **kwargs):
        raise RuntimeError("Falha simulada.")

    assert agente_local.executar("oi", chamar=falhar)["texto"] == agente_local.DESISTENCIA
    monkeypatch.setattr(agente_local.acoes, "executar", falhar)
    assert agente_local.confirmar({"acao": "abrir", "args": {}, "pedido": "oi"}) == {
        "texto": agente_local.DESISTENCIA, "pendente": None, "passos": [],
    }
    assert agente_local.confirmar(None)["texto"] == agente_local.DESISTENCIA
