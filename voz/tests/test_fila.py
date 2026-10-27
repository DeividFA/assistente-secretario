"""Testes da fila com bancos temporários e modelo falso."""

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fila


@pytest.mark.parametrize("texto, prioridade, limpo", [
    ("URGÊNCIA, abre o e-mail", 0, "abre o e-mail"),
    ("agora: abre", 0, "abre"),
    ("imediatamente abre", 0, "abre"),
    ("primeiro, leia", 1, "leia"),
    ("antes leia", 1, "leia"),
    ("rápido: leia", 1, "leia"),
    ("Depois, leia", 3, "leia"),
    ("quando puder, leia", 3, "leia"),
    ("mais tarde leia", 3, "leia"),
    ("sem pressa: leia", 3, "leia"),
    ("leia o urgente aviso", 0, "leia o urgente aviso"),
    ("depois leia agora", 0, "leia agora"),
    ("abrir diariamente", 2, "abrir diariamente"),
    ("", 2, ""),
])
def test_prioridade(texto, prioridade, limpo):
    assert fila.detectar_prioridade(texto) == (prioridade, limpo)


def test_ordem_e_ciclo(tmp_path):
    banco = tmp_path / "secretario.db"
    antigo = fila.adicionar("antigo", banco=banco)
    novo = fila.adicionar("novo", banco=banco)
    urgente = fila.adicionar("urgente", 0, "gemma", banco=banco)
    with sqlite3.connect(banco) as conexao:
        conexao.execute("UPDATE fila SET criado = '2026-01-01' WHERE id IN (?, ?)", (antigo, novo))
    assert [t["id"] for t in fila.listar(banco=banco)] == [urgente, antigo, novo]
    for id in (urgente, antigo, novo):
        tarefa = fila.proxima(banco=banco)
        assert tarefa["id"] == id
        assert tarefa["status"] == "rodando"
        assert tarefa["inicio"]
        fila.concluir(id, "concluida", "Pronto", banco=banco)
    assert fila.proxima(banco=banco) is None
    assert fila.listar(banco=banco) == []
    assert all(t["fim"] and t["resposta"] == "Pronto" for t in fila.listar(False, banco=banco))


def test_cancelar_e_recuperar(tmp_path):
    banco = tmp_path / "fila.db"
    ids = [fila.adicionar(str(i), banco=banco) for i in range(4)]
    fila.proxima(banco=banco)
    assert fila.cancelar(ids[0], banco=banco)
    assert fila.cancelar(ids[1], banco=banco)
    assert not fila.cancelar(ids[0], banco=banco)
    assert not fila.cancelar(999, banco=banco)
    fila.concluir(ids[0], "concluida", banco=banco)
    assert fila.proxima(banco=banco)["id"] == ids[2]
    fila.recuperar(banco=banco)
    ativas = fila.listar(banco=banco)
    assert [t["id"] for t in ativas] == ids[2:]
    assert all(t["status"] == "pendente" and t["inicio"] is None for t in ativas)
    fila.recuperar(banco=banco)
    assert fila.proxima(banco=banco)["id"] == ids[2]
    fila.concluir(ids[2], "erro", "Falhou", banco=banco)
    assert not fila.cancelar(ids[2], banco=banco)
    assert fila.listar(False, banco=banco)[0]["status"] == "cancelada"


def test_reserva_concorrente(tmp_path):
    banco = tmp_path / "fila.db"
    ids = [fila.adicionar(str(i), banco=banco) for i in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        tarefas = list(executor.map(lambda _: fila.proxima(banco=banco), ids))
    assert sorted(t["id"] for t in tarefas) == ids
    assert fila.proxima(banco=banco) is None


@pytest.mark.parametrize("saida, esperado", [
    ('{"pedidos": ["abre o e-mail", "consulta a previsão"]}', ["abre o e-mail", "consulta a previsão"]),
    ('{"pedidos": ["abre o e-mail e depois responde o primeiro"]}', ["abre o e-mail e depois responde o primeiro"]),
    ("inválido", None),
    ('{"pedidos": []}', None),
    ('{"pedidos": [null]}', None),
    ('{"pedidos": [" "]}', None),
    ('{"pedidos": ["1", "2", "3", "4", "5"]}', None),
    ('[]', None),
])
def test_dividir(saida, esperado):
    texto = "abre o e-mail e depois responde o primeiro"
    chamadas = []

    def chamar(mensagens):
        chamadas.append(mensagens)
        return saida
    assert fila.dividir_pedidos(texto, chamar) == (esperado or [texto])
    assert len(chamadas) == 1
    assert texto in chamadas[0][0]["content"]
    assert chamadas[0][1]["content"] == texto


@pytest.mark.parametrize("conector", fila.CONECTORES)
def test_conectores(conector):
    texto = "leia " + conector + " pesquise"
    assert fila.dividir_pedidos(texto, lambda _: '{"pedidos":["leia","pesquise"]}') == ["leia", "pesquise"]


def test_sem_conector_e_falha():
    chamadas = []

    def falhar(_):
        chamadas.append(True)
        raise OSError("Modelo indisponível")
    assert fila.dividir_pedidos("leia o e-mail", falhar) == ["leia o e-mail"]
    assert chamadas == []
    texto = "leia e também pesquise"
    assert fila.dividir_pedidos(texto, falhar) == [texto]
    assert chamadas == [True]


def test_compartilha_banco_com_registro(tmp_path):
    import registro

    banco = tmp_path / "secretario.db"
    registro.evento("Você", "Olá", banco=banco)
    fila.adicionar("Pedido", banco=banco)
    registro.evento("Secretário", "Certo", banco=banco)
    with sqlite3.connect(banco) as conexao:
        assert conexao.execute("SELECT COUNT(*) FROM eventos").fetchone()[0] == 2
        assert conexao.execute("SELECT COUNT(*) FROM fila").fetchone()[0] == 1


def test_validacao(tmp_path):
    banco = tmp_path / "fila.db"
    with pytest.raises(ValueError):
        fila.adicionar("Pedido", prioridade=4, banco=banco)
    with pytest.raises(ValueError):
        fila.concluir(1, "pendente", banco=banco)
