"""Fila persistente de pedidos, com prioridade e reserva atômica."""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

BANCO = Path(__file__).resolve().parent / "secretario.db"
GATILHOS = (
    (0, ("urgente", "urgencia", "agora", "imediatamente")),
    (1, ("primeiro", "antes", "rapido")),
    (3, ("depois", "quando puder", "mais tarde", "sem pressa")),
)
CONECTORES = ("e tambem", "e depois", "alem disso", "outra coisa", "e em seguida")


def detectar_prioridade(texto):
    from comum import normalizar

    palavras = list(re.finditer(r"\w+", texto))
    normalizado = " ".join(normalizar(p.group()) for p in palavras)
    prioridade = 2
    for valor, gatilhos in GATILHOS:
        for gatilho in gatilhos:
            # "urgente/agora" valem em qualquer lugar; "primeiro/antes" só no começo e
            # "depois/quando puder" no começo ou no fim — senão "abre o e-mail e depois
            # responde o primeiro" mudaria de prioridade.
            padrao = {0: rf"\b{gatilho}\b", 1: rf"^{gatilho}\b"}.get(valor, rf"^{gatilho}\b|\b{gatilho}$")
            if re.search(padrao, normalizado):
                prioridade = valor
                break
        if prioridade != 2:
            break
    for _, gatilhos in GATILHOS:
        for gatilho in gatilhos:
            if normalizado == gatilho or normalizado.startswith(gatilho + " "):
                fim = palavras[len(gatilho.split()) - 1].end()
                return prioridade, texto[fim:].lstrip(" \t\r\n,;:.-!?—–")
    return prioridade, texto


def _chamar(mensagens):
    dados = json.dumps({
        "model": "gemma3:4b", "messages": mensagens, "format": "json",
        "stream": False, "keep_alive": "30m", "options": {"temperature": 0.1},
    }).encode("utf-8")
    pedido = Request("http://localhost:11434/api/chat", data=dados,
                     headers={"Content-Type": "application/json"})
    with urlopen(pedido, timeout=120) as resposta:
        return json.loads(resposta.read().decode("utf-8"))["message"]["content"]


def dividir_pedidos(texto, chamar=None):
    from comum import normalizar

    normalizado = " " + " ".join(normalizar(texto).split()) + " "
    if not any(" " + conector + " " in normalizado for conector in CONECTORES):
        return [texto]
    mensagens = [
        {"role": "system", "content": (
            'Separe somente pedidos independentes. Retorne JSON {"pedidos": ["..."]}, '
            'com no máximo 4 pedidos, sem inventar nem omitir informações. '
            'Pedidos ligados entre si devem continuar como UM pedido: '
            '"abre o e-mail e depois responde o primeiro" deve permanecer inteiro. '
            'Se não houver divisão possível, retorne o pedido original na lista.')},
        {"role": "user", "content": texto},
    ]
    try:
        dados = json.loads((chamar or _chamar)(mensagens))
        pedidos = dados.get("pedidos")
        if not isinstance(pedidos, list) or not pedidos or len(pedidos) > 4:
            return [texto]
        if not all(isinstance(p, str) and p.strip() for p in pedidos):
            return [texto]
        return [p.strip() for p in pedidos]
    except Exception:
        return [texto]


def _conectar(banco):
    conexao = sqlite3.connect(banco, timeout=30)
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS fila (
                id INTEGER PRIMARY KEY, criado TEXT, comando TEXT, prioridade INTEGER,
                status TEXT, motor TEXT, inicio TEXT, fim TEXT, resposta TEXT
            )
        """)
        return conexao
    except Exception:
        conexao.close()
        raise


def adicionar(comando, prioridade=2, motor="claude", banco=BANCO):
    if prioridade not in (0, 1, 2, 3):
        raise ValueError("Prioridade inválida.")
    conexao = _conectar(banco)
    try:
        with conexao:
            cursor = conexao.execute(
                "INSERT INTO fila (criado, comando, prioridade, status, motor) VALUES (?, ?, ?, 'pendente', ?)",
                (datetime.now().isoformat(), comando, prioridade, motor))
            return cursor.lastrowid
    finally:
        conexao.close()


def proxima(banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            conexao.execute("BEGIN IMMEDIATE")
            tarefa = conexao.execute(
                "SELECT * FROM fila WHERE status = 'pendente' ORDER BY prioridade, criado, id LIMIT 1"
            ).fetchone()
            if tarefa is None:
                return None
            inicio = datetime.now().isoformat()
            conexao.execute("UPDATE fila SET status = 'rodando', inicio = ? WHERE id = ?",
                            (inicio, tarefa["id"]))
            return dict(tarefa, status="rodando", inicio=inicio)
    finally:
        conexao.close()


def concluir(id, status, resposta="", banco=BANCO):
    if status not in ("concluida", "erro", "cancelada"):
        raise ValueError("Status final inválido.")
    conexao = _conectar(banco)
    try:
        with conexao:
            conexao.execute(
                "UPDATE fila SET status = ?, fim = ?, resposta = ? WHERE id = ? AND status IN ('pendente', 'rodando')",
                (status, datetime.now().isoformat(), resposta, id))
    finally:
        conexao.close()


def cancelar(id, banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            cursor = conexao.execute(
                "UPDATE fila SET status = 'cancelada', fim = ? WHERE id = ? AND status IN ('pendente', 'rodando')",
                (datetime.now().isoformat(), id))
            return cursor.rowcount > 0
    finally:
        conexao.close()


def listar(ativas=True, banco=BANCO):
    conexao = _conectar(banco)
    try:
        filtro = " WHERE status IN ('pendente', 'rodando')" if ativas else ""
        return [dict(linha) for linha in conexao.execute(
            "SELECT * FROM fila" + filtro + " ORDER BY prioridade, criado, id")]
    finally:
        conexao.close()


def recuperar(banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            conexao.execute(
                "UPDATE fila SET status = 'pendente', inicio = NULL, fim = NULL WHERE status = 'rodando'")
    finally:
        conexao.close()
