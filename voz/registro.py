"""Registro de eventos e tarefas em SQLite, com uma conexão por chamada."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BANCO = Path(__file__).resolve().parent / "secretario.db"


def preparar_banco():
    """Cria o banco inicial sem modificar um banco já existente."""
    if not BANCO.exists():
        _conectar(BANCO).close()


def _conectar(banco):
    conexao = sqlite3.connect(banco, timeout=30)
    try:
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS bugs (
                id INTEGER PRIMARY KEY, assinatura TEXT UNIQUE, tipo TEXT, resumo TEXT,
                traceback TEXT, contexto TEXT, primeira_vez TEXT, ultima_vez TEXT,
                ocorrencias INTEGER NOT NULL DEFAULT 1, estado TEXT NOT NULL DEFAULT 'novo',
                diretriz TEXT DEFAULT '', "commit" TEXT DEFAULT '',
                tentativas INTEGER NOT NULL DEFAULT 0, avisado_em TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY, ts TEXT, autor TEXT, texto TEXT,
                sessao TEXT, motor TEXT
            );
            CREATE TABLE IF NOT EXISTS tarefas (
                id INTEGER PRIMARY KEY, inicio TEXT, fim TEXT, comando TEXT,
                motor TEXT, status TEXT, ferramentas TEXT, resposta TEXT,
                duracao_ms INTEGER
            );
        """)
        return conexao
    except Exception:
        conexao.close()
        raise


def evento(autor, texto, sessao=None, motor=None, banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            conexao.execute(
                "INSERT INTO eventos (ts, autor, texto, sessao, motor) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), autor, texto, sessao, motor))
    finally:
        conexao.close()


def inicio_tarefa(comando, motor, banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            cursor = conexao.execute(
                "INSERT INTO tarefas (inicio, comando, motor) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), comando, motor))
            return cursor.lastrowid
    finally:
        conexao.close()


def fim_tarefa(id, status, resposta="", ferramentas=(), banco=BANCO):
    if status not in ("ok", "erro", "cancelada"):
        raise ValueError("Status de tarefa inválido.")
    conexao = _conectar(banco)
    try:
        with conexao:
            tarefa = conexao.execute("SELECT inicio FROM tarefas WHERE id = ?", (id,)).fetchone()
            if tarefa is None:
                raise ValueError("Tarefa não encontrada.")
            fim = datetime.now()
            duracao = max(0, int((fim - datetime.fromisoformat(tarefa["inicio"])).total_seconds() * 1000))
            conexao.execute(
                "UPDATE tarefas SET fim = ?, status = ?, ferramentas = ?, resposta = ?, duracao_ms = ? WHERE id = ?",
                (fim.isoformat(), status, json.dumps(list(ferramentas), ensure_ascii=False), resposta, duracao, id))
    finally:
        conexao.close()


def ultimas_tarefas(n=20, banco=BANCO):
    conexao = _conectar(banco)
    try:
        return [dict(linha) for linha in conexao.execute(
            "SELECT * FROM tarefas ORDER BY inicio DESC, id DESC LIMIT ?", (max(0, n),))]
    finally:
        conexao.close()


def salvar_bug(assinatura, tipo, resumo, traceback, contexto, banco=BANCO):
    conexao = _conectar(banco)
    try:
        with conexao:
            agora = datetime.now().isoformat()
            conexao.execute("""INSERT INTO bugs
                (assinatura, tipo, resumo, traceback, contexto, primeira_vez, ultima_vez)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(assinatura) DO UPDATE SET
                ultima_vez=excluded.ultima_vez, ocorrencias=bugs.ocorrencias+1""",
                (assinatura, tipo, resumo, traceback, json.dumps(contexto, ensure_ascii=False), agora, agora))
            return conexao.execute("SELECT id FROM bugs WHERE assinatura=?", (assinatura,)).fetchone()[0]
    finally:
        conexao.close()


def listar_bugs(banco=BANCO):
    conexao = _conectar(banco)
    try:
        return [dict(linha) for linha in conexao.execute("SELECT * FROM bugs ORDER BY ultima_vez DESC")]
    finally:
        conexao.close()


def detalhe_bug(id, banco=BANCO):
    return next((bug for bug in listar_bugs(banco) if bug['id'] == int(id)), None)


def atualizar_bug(id, banco=BANCO, **campos):
    permitidos = {'estado', 'diretriz', 'commit', 'tentativas', 'avisado_em'}
    if not campos or not set(campos) <= permitidos:
        raise ValueError('Campos de bug inválidos.')
    if 'estado' in campos and campos['estado'] not in (
            'novo', 'informado', 'aprovado', 'corrigindo', 'corrigido', 'falhou', 'ignorado'):
        raise ValueError('Estado de bug inválido.')
    conexao = _conectar(banco)
    try:
        with conexao:
            conexao.execute('UPDATE bugs SET ' + ', '.join('"' + c + '"=?' for c in campos)
                            + ' WHERE id=?', (*campos.values(), int(id)))
    finally:
        conexao.close()


def eventos_recentes(banco=BANCO):
    conexao = _conectar(banco)
    try:
        return [dict(linha) for linha in conexao.execute(
            "SELECT * FROM eventos WHERE ts >= ? ORDER BY id",
            ((datetime.now() - timedelta(hours=1)).isoformat(),))]
    finally:
        conexao.close()


def ultimo_evento(autor, banco=BANCO):
    conexao = _conectar(banco)
    try:
        linha = conexao.execute('SELECT * FROM eventos WHERE autor=? ORDER BY id DESC LIMIT 1',
                                (autor,)).fetchone()
        return dict(linha) if linha else None
    finally:
        conexao.close()
