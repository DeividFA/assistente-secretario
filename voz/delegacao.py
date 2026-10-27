"""Trabalhos delegados a agentes CLI, em threads e com histórico em SQLite."""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import motores_cli
import registro


_trabalhos = {}
_trava = threading.RLock()


def _conectar():
    conexao = sqlite3.connect(registro.BANCO, timeout=30)
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS delegacoes (
                id TEXT PRIMARY KEY, agente TEXT, tarefa TEXT, pasta TEXT,
                status TEXT, inicio TEXT, fim TEXT, resposta TEXT, ferramentas TEXT
            )
        """)
        return conexao
    except Exception:
        conexao.close()
        raise


def _publico(trabalho):
    return {chave: list(trabalho[chave]) if chave == "ferramentas" else trabalho[chave]
            for chave in ("id", "agente", "status", "inicio", "fim", "resposta", "ferramentas")}


def _salvar(trabalho):
    conexao = _conectar()
    try:
        with conexao:
            conexao.execute("""
                INSERT OR REPLACE INTO delegacoes
                (id, agente, tarefa, pasta, status, inicio, fim, resposta, ferramentas)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trabalho["id"], trabalho["agente"], trabalho["tarefa"], trabalho["pasta"],
                  trabalho["status"], trabalho["inicio"], trabalho["fim"], trabalho["resposta"],
                  json.dumps(trabalho["ferramentas"], ensure_ascii=False)))
    finally:
        conexao.close()


def _historico():
    conexao = _conectar()
    try:
        trabalhos = []
        for linha in conexao.execute("SELECT * FROM delegacoes ORDER BY inicio DESC"):
            trabalho = dict(linha)
            trabalho["ferramentas"] = json.loads(trabalho["ferramentas"])
            trabalhos.append(_publico(trabalho))
        return trabalhos
    finally:
        conexao.close()


def iniciar(agente, tarefa, pasta=None):
    if "SECRETARIO_DELEGACAO" in os.environ:
        raise ValueError("delegação aninhada não permitida")
    if agente not in motores_cli.EXECUTAVEIS:
        raise ValueError("Agente de linha de comando desconhecido.")
    if not isinstance(tarefa, str) or not tarefa.strip():
        raise ValueError("Informe uma tarefa de trabalho.")
    caminho = Path(pasta).expanduser().resolve() if pasta else Path.home()
    if not caminho.is_dir():
        raise ValueError("A pasta de trabalho não existe.")
    ambiente = dict(os.environ, SECRETARIO_DELEGACAO="1")
    with _trava:
        # Uma tarefa cancelada ainda ocupa vaga até a thread encerrar o filho.
        if sum(t["ativo"] for t in _trabalhos.values()) >= 3:
            raise ValueError("Máximo de 3 delegações rodando ao mesmo tempo.")
        id = uuid4().hex
        trabalho = {"id": id, "agente": agente, "tarefa": tarefa, "pasta": str(caminho),
                    "status": "rodando", "inicio": datetime.now().isoformat(), "fim": None,
                    "resposta": "", "ferramentas": [], "proc": None, "ativo": True}
        _salvar(trabalho)
        _trabalhos[id] = trabalho
        try:
            threading.Thread(target=_executar, args=(trabalho, ambiente), daemon=True).start()
        except Exception as erro:
            trabalho.update(status="erro", fim=datetime.now().isoformat(),
                            resposta=str(erro)[:4000], ativo=False)
            _salvar(trabalho)
            raise
        return id


def _executar(trabalho, ambiente):
    def evento(dados):
        proc = None
        with _trava:
            if dados["tipo"] == "processo":
                trabalho["proc"] = dados["proc"]
                if trabalho["status"] == "cancelada":
                    proc = dados["proc"]
            elif trabalho["status"] == "rodando":
                if dados["tipo"] == "ferramenta":
                    trabalho["ferramentas"].append(dados["nome"])
                elif dados["tipo"] == "resposta":
                    trabalho["resposta"] = dados["texto"][:4000]
                _salvar(trabalho)
        if proc is not None:
            motores_cli._matar_arvore(proc)

    try:
        with _trava:
            if trabalho["status"] == "cancelada":
                return
        resultado = motores_cli.executar(trabalho["agente"], trabalho["tarefa"], evento,
                                        pasta=trabalho["pasta"], env=ambiente)
        with _trava:
            if trabalho["status"] == "rodando":
                trabalho.update(status="ok", resposta=resultado["resposta"][:4000],
                                ferramentas=list(resultado["ferramentas"]))
    except Exception as erro:
        with _trava:
            if trabalho["status"] == "rodando":
                trabalho.update(status="erro", resposta=str(erro)[:4000])
    finally:
        with _trava:
            trabalho.update(ativo=False, proc=None, fim=datetime.now().isoformat())
            _salvar(trabalho)


def estado(id):
    with _trava:
        if id in _trabalhos:
            return _publico(_trabalhos[id])
        for trabalho in _historico():
            if trabalho["id"] == id:
                return trabalho
    raise ValueError("Delegação não encontrada.")


def cancelar(id):
    with _trava:
        trabalho = _trabalhos.get(id)
        if trabalho is None:
            anterior = estado(id)
            if anterior["status"] == "rodando":
                raise ValueError("Delegação pertence a outro processo; não é possível cancelá-la aqui.")
            return anterior
        if trabalho["status"] != "rodando":
            return _publico(trabalho)
        trabalho.update(status="cancelada", fim=datetime.now().isoformat())
        _salvar(trabalho)
        proc = trabalho["proc"]
    if proc is not None:
        motores_cli._matar_arvore(proc)
    return estado(id)


def listar():
    with _trava:
        trabalhos = {t["id"]: t for t in _historico()}
        trabalhos.update({id: _publico(t) for id, t in _trabalhos.items()})
        return sorted(trabalhos.values(), key=lambda t: t["inicio"], reverse=True)
