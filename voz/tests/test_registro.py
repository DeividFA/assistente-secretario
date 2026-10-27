"""Testes do registro usando somente bancos temporários."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import registro


def test_evento_cria_tabelas_e_usa_wal(tmp_path):
    banco = tmp_path / "registro.db"
    registro.evento("Você", "Olá", sessao="sessao-1", motor="claude", banco=banco)
    with sqlite3.connect(banco) as conexao:
        tabelas = {linha[0] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"eventos", "tarefas"} <= tabelas
        assert conexao.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conexao.execute("SELECT autor, texto, sessao, motor FROM eventos").fetchone() == (
            "Você", "Olá", "sessao-1", "claude")


@pytest.mark.parametrize("status", ["ok", "erro", "cancelada"])
def test_ciclo_tarefa(tmp_path, status):
    banco = tmp_path / "registro.db"
    id = registro.inicio_tarefa("Leia o arquivo", "claude", banco=banco)
    registro.fim_tarefa(id, status, "Pronto", ["Read"], banco=banco)
    tarefa = registro.ultimas_tarefas(banco=banco)[0]
    assert tarefa["id"] == id
    assert tarefa["status"] == status
    assert tarefa["resposta"] == "Pronto"
    assert tarefa["comando"] == "Leia o arquivo"
    assert tarefa["motor"] == "claude"
    assert tarefa["fim"] >= tarefa["inicio"]
    assert isinstance(tarefa["duracao_ms"], int)
    assert tarefa["duracao_ms"] >= 0
    assert json.loads(tarefa["ferramentas"]) == ["Read"]


def test_ultimas_tarefas_ordena_e_limita(tmp_path):
    banco = tmp_path / "registro.db"
    ids = [registro.inicio_tarefa(str(i), "gemma", banco=banco) for i in range(3)]
    assert [t["id"] for t in registro.ultimas_tarefas(2, banco=banco)] == ids[::-1][:2]
    assert registro.ultimas_tarefas(0, banco=banco) == []


def test_status_invalido(tmp_path):
    banco = tmp_path / "registro.db"
    id = registro.inicio_tarefa("Pedido", "gemma", banco=banco)
    with pytest.raises(ValueError):
        registro.fim_tarefa(id, "desconhecido", banco=banco)
