"""Gastos em centavos; o cofre recebe somente totais por categoria."""

from datetime import date
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import threading

import registro

COFRE = Path.home() / 'Documents' / 'Secretario'
_trava = threading.RLock()
CAMPOS = ('id', 'data', 'valor_centavos', 'descricao', 'estabelecimento',
          'categoria', 'forma', 'origem', 'confirmado')


@contextmanager
def conectar(banco):
    con = sqlite3.connect(banco, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            preparar(con)
            yield con
    finally:
        con.close()


def preparar(con):
    con.execute('''CREATE TABLE IF NOT EXISTS gastos (
        aparelho INTEGER NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
        valor_centavos INTEGER NOT NULL CHECK(valor_centavos > 0),
        descricao TEXT NOT NULL, estabelecimento TEXT NOT NULL, categoria TEXT NOT NULL,
        forma TEXT NOT NULL, origem TEXT NOT NULL, confirmado INTEGER NOT NULL,
        PRIMARY KEY(aparelho, id))''')


def validar(item):
    if not isinstance(item, dict) or set(item) != set(CAMPOS):
        raise ValueError('Campos de gasto inválidos')
    if not isinstance(item['id'], str) or not re.fullmatch(r'[\w:-]{1,100}', item['id']):
        raise ValueError('Id inválido')
    if not isinstance(item['data'], str) or date.fromisoformat(item['data']).isoformat() != item['data']:
        raise ValueError('Data inválida')
    if type(item['valor_centavos']) is not int or not 0 < item['valor_centavos'] <= 10**12:
        raise ValueError('Use centavos inteiros positivos')
    if type(item['confirmado']) is not bool:
        raise ValueError('Confirmação inválida')
    if item['origem'] not in ('voz', 'foto', 'notificacao', 'csv'):
        raise ValueError('Origem inválida')
    limpo = {chave: item[chave] for chave in CAMPOS}
    for campo in ('descricao', 'estabelecimento', 'categoria', 'forma'):
        if not isinstance(item[campo], str) or len(item[campo]) > 120:
            raise ValueError('Campo inválido')
        # Mascara números longos (cartão/conta) em vez de recusar: "Padaria 2000" não pode
        # derrubar o lote inteiro. Quebras de linha indicam texto integral de comprovante.
        limpo[campo] = re.sub(r'\d{4,}', '****', ' '.join(item[campo].split()))
    return limpo


def listar(aparelho, desde='', banco=registro.BANCO):
    if desde:
        if date.fromisoformat(desde).isoformat() != desde:
            raise ValueError('Data inválida')
    with conectar(banco) as con:
        itens = [dict(r) for r in con.execute(
            'SELECT ' + ','.join(CAMPOS) + ' FROM gastos WHERE aparelho=? AND data>=? ORDER BY data,id',
            (aparelho, desde))]
    for item in itens:
        item['confirmado'] = bool(item['confirmado'])
    return itens


def receber(aparelho, itens, banco=registro.BANCO, cofre=None):
    if not isinstance(itens, list) or not 1 <= len(itens) <= 50:
        raise ValueError('Envie de 1 a 50 gastos')
    limpos = [validar(item) for item in itens]
    cofre = COFRE if cofre is None else cofre
    meses = {item['data'][:7] for item in limpos}
    with _trava:
        with conectar(banco) as con:
            for item in limpos:
                anterior = con.execute('SELECT data FROM gastos WHERE aparelho=? AND id=?',
                                       (aparelho, item['id'])).fetchone()
                # Datas/valores podem ser corrigidos mantendo a identidade local.
                con.execute('INSERT INTO gastos (aparelho,' + ','.join(CAMPOS) + ') VALUES (' +
                            ','.join('?' for _ in range(10)) + ') ON CONFLICT(aparelho,id) DO UPDATE SET ' +
                            ','.join(f'{c}=excluded.{c}' for c in CAMPOS if c != 'id'),
                            (aparelho, *(item[c] for c in CAMPOS)))
                if anterior:
                    meses.add(anterior[0][:7])
        for mes in meses:
            gerar_nota(mes, banco=banco, cofre=cofre)
    return [item['id'] for item in limpos]


def reais(centavos):
    return f'R$ {centavos // 100},{centavos % 100:02d}'


def gerar_nota(mes, banco=registro.BANCO, cofre=COFRE):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', mes):
        raise ValueError('Mês inválido')
    with _trava:
        with conectar(banco) as con:
            linhas = list(con.execute('SELECT categoria, SUM(valor_centavos) FROM gastos '
                                     'WHERE confirmado=1 AND substr(data,1,7)=? GROUP BY categoria ORDER BY categoria', (mes,)))
        destino = Path(cofre) / 'Finanças' / f'Gastos {mes}.md'
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Categorias viram texto simples, sem links ou metadados vindos do aparelho.
        texto = f'# Gastos {mes}\n\nTotal: {reais(sum(r[1] for r in linhas))}\n\n'
        for categoria, total in linhas:
            categoria = re.sub(r'[^\w À-ÿ-]', '', categoria)
            texto += f'- {categoria}: {reais(total)}\n'
        temporario = destino.with_suffix('.md.tmp')
        temporario.write_text(texto, encoding='utf-8')
        temporario.replace(destino)
    return destino
