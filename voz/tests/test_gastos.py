"""Somente bancos e cofre temporários; sem acessar dados pessoais."""

import asyncio
import hashlib
from pathlib import Path
import sqlite3
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gastos
import ponte


def item(**mudancas):
    return dict(dict(id='local-1', data='2026-10-26', valor_centavos=4500,
                     descricao='Gasto', estabelecimento='Mercado', categoria='Mercado',
                     forma='Pix', origem='voz', confirmado=True), **mudancas)


def test_reenvio_correcao_e_isolamento_por_aparelho(tmp_path):
    banco, cofre = tmp_path / 'teste.db', tmp_path / 'cofre'
    with sqlite3.connect(banco) as con:
        con.execute('CREATE TABLE mensagens(texto TEXT)')
        con.execute("INSERT INTO mensagens VALUES ('preservar')")
    for _ in range(2):
        assert gastos.receber(1, [item()], banco, cofre) == ['local-1']
    gastos.receber(2, [item(valor_centavos=123456)], banco, cofre)
    assert len(gastos.listar(1, banco=banco)) == 1
    assert gastos.listar(2, banco=banco)[0]['valor_centavos'] == 123456
    gastos.receber(1, [item(data='2026-11-01', categoria='Casa')], banco, cofre)
    assert gastos.listar(1, '2026-11-01', banco)[0]['categoria'] == 'Casa'
    assert gastos.listar(1, '2026-11-02', banco) == []
    with sqlite3.connect(banco) as con:
        assert con.execute('SELECT texto FROM mensagens').fetchone()[0] == 'preservar'
        assert con.execute('SELECT COUNT(*) FROM gastos').fetchone()[0] == 2
    outubro = (cofre / 'Finanças/Gastos 2026-10.md').read_text(encoding='utf-8')
    assert 'R$ 1234,56' in outubro and 'R$ 1279,56' not in outubro


@pytest.mark.parametrize('mudancas', [dict(valor_centavos=45.0), dict(valor_centavos=True),
    dict(valor_centavos='4500'), dict(valor_centavos=-1), dict(valor_centavos=0),
    dict(valor_centavos=10**13), dict(data='2026-02-30'), dict(data='20261026'),
    dict(confirmado=1), dict(origem='banco'), dict(id='../cofre')])
def test_validacao_atomica(tmp_path, mudancas):
    banco, cofre = tmp_path / 'teste.db', tmp_path / 'cofre'
    with pytest.raises((ValueError, TypeError)):
        gastos.receber(1, [item(), item(**mudancas)], banco, cofre)
    assert not banco.exists() and not cofre.exists()


def test_nota_so_confirmados_e_totais_sem_cartao(tmp_path):
    banco, cofre = tmp_path / 'teste.db', tmp_path / 'cofre'
    gastos.receber(1, [item(), item(id='pendente', valor_centavos=9999, confirmado=False),
                       item(id='outro', estabelecimento='Farmácia', categoria='Saúde', valor_centavos=1234)], banco, cofre)
    texto = (cofre / 'Finanças/Gastos 2026-10.md').read_text(encoding='utf-8')
    assert 'Total: R$ 57,34' in texto and 'Saúde: R$ 12,34' in texto
    assert 'Farmácia' not in texto and 'Pix' not in texto and '99,99' not in texto


def test_endpoints_autenticados_invalidos_reenvio_e_filtro(tmp_path, monkeypatch):
    monkeypatch.setattr(gastos, 'COFRE', tmp_path / 'cofre')
    async def verificar():
        p = ponte.Ponte(None, None, banco=tmp_path / 'teste.db')
        token = 'a' * 64
        with p.conectar() as con:
            con.execute("INSERT INTO aparelhos (hash, criado, ultimo_uso) VALUES (?, ?, ?)",
                        (hashlib.sha256(token.encode()).hexdigest(), '2026-10-27', '2026-10-27'))
        headers = {'Authorization': 'Bearer ' + token}
        async with TestClient(TestServer(p.criar_app())) as cliente:
            assert (await cliente.post('/gastos', json={'gastos': [item()]})).status == 401
            assert (await cliente.get('/gastos')).status == 401
            for _ in range(2):
                r = await cliente.post('/gastos', headers=headers, json={'gastos': [item()]})
                assert r.status == 200 and await r.json() == {'ids': ['local-1']}
            r = await cliente.get('/gastos?desde=2026-10-01', headers=headers)
            assert await r.json() == {'gastos': [item()]}
            r = await cliente.get('/gastos?desde=2026-11-01', headers=headers)
            assert await r.json() == {'gastos': []}
            for dados in ({}, [], {'gastos': []}, {'gastos': [item(valor_centavos=45.5)]},
                          {'gastos': [item(texto_completo='não guardar')]}):
                assert (await cliente.post('/gastos', headers=headers, json=dados)).status == 400
            assert (await cliente.get('/gastos?desde=ontem', headers=headers)).status == 400
            with p.conectar() as con:
                auditoria = '\n'.join(r[0] for r in con.execute('SELECT texto FROM eventos'))
            assert 'Mercado' not in auditoria and token not in auditoria
            await p.revogar(1)
            assert (await cliente.get('/gastos', headers=headers)).status == 401
    asyncio.run(verificar())


def test_numeros_longos_sao_mascarados_sem_recusar_o_lote(tmp_path):
    banco, cofre = tmp_path / 'teste.db', tmp_path / 'cofre'
    gastos.receber(1, [item(id='a', estabelecimento='Padaria 2000'),
                       item(id='b', forma='cartão 1234567890123456', descricao='texto\ncompleto')],
                   banco, cofre)
    salvos = {g['id']: g for g in gastos.listar(1, banco=banco)}
    assert salvos['a']['estabelecimento'] == 'Padaria ****'
    assert salvos['b']['forma'] == 'cartão ****' and salvos['b']['descricao'] == 'texto completo'
