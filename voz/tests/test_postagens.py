"""C6 usa apenas cofre temporário; não chama IA nem o motor."""

import asyncio
from datetime import datetime
from pathlib import Path
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memoria
import ponte
from test_ponte import preparar


def test_resumo_perfil_estilo_sem_dados_sensiveis(tmp_path):
    (tmp_path / 'Perfil').mkdir()
    (tmp_path / 'Preferências').mkdir()
    (tmp_path / 'Perfil' / 'Deivid.md').write_text(
        '# Perfil\nGosta de tecnologia\nCPF: 123.456.789-00\nRG: 12345\n'
        'Endereço: Rua das Flores\nTelefone: (11) 99999-9999\n'
        'Rua das Rosas\nContato: deivid@example.com\n', encoding='utf-8')
    (tmp_path / 'Preferências' / 'Estilo.md').write_text(
        '---\ntelefone: segredo\n---\n# Estilo\n- 2026-10-27 — Prefere frases curtas\n', encoding='utf-8')
    resumo = memoria.perfil_estilo(tmp_path)
    assert 'Gosta de tecnologia' in resumo
    assert 'Prefere frases curtas' in resumo
    for sensivel in ('CPF', 'RG', 'Flores', 'Rosas', '9999', 'example.com', 'segredo'):
        assert sensivel not in resumo
    assert len(resumo) <= 1600
    assert memoria.perfil_estilo(tmp_path / 'ausente') == ''


def test_resumo_limitado(tmp_path):
    (tmp_path / 'Perfil').mkdir()
    (tmp_path / 'Perfil' / 'Estilo.md').write_text(('Texto curto\n' * 1000), encoding='utf-8')
    assert len(memoria.perfil_estilo(tmp_path)) <= 1600


def test_historico_idempotente_em_uma_linha(tmp_path):
    for _ in range(2):
        memoria.registrar_postagem('abc-123', 'LinkedIn', 'Olá\nmundo', tmp_path, datetime(2026, 10, 27, 12))
    texto = (tmp_path / 'Histórico' / 'Postagens.md').read_text(encoding='utf-8')
    assert texto.count('postagem:abc-123') == 1
    assert '2026-10-27T12:00:00 — LinkedIn: Olá mundo' in texto
    with pytest.raises(ValueError):
        memoria.registrar_postagem('../x', 'LinkedIn', 'texto', tmp_path)
    with pytest.raises(ValueError):
        memoria.registrar_postagem('x', 'Outra', 'texto', tmp_path)


def test_rotas_postagens_e_perfil_autenticadas(tmp_path, monkeypatch):
    ler = memoria.perfil_estilo
    guardar = memoria.registrar_postagem
    cofre = tmp_path / 'cofre'
    monkeypatch.setattr(ponte.memoria, 'perfil_estilo', lambda: ler(cofre))
    monkeypatch.setattr(ponte.memoria, 'registrar_postagem', lambda id, rede, texto: guardar(id, rede, texto, cofre))

    async def verificar():
        p, headers, _ = preparar(tmp_path)
        async with TestClient(TestServer(p.criar_app())) as cliente:
            assert (await cliente.get('/memoria/perfil-estilo')).status == 401
            assert (await cliente.post('/postagens', json={})).status == 401
            resposta = await cliente.get('/memoria/perfil-estilo', headers=headers)
            assert await resposta.json() == {'resumo': ''}
            for dados in ([], {}, {'id': 'x', 'rede': 'Instagram', 'texto': ''},
                          {'id': 'x', 'rede': [], 'texto': 'texto'}):
                assert (await cliente.post('/postagens', json=dados, headers=headers)).status == 400
            for _ in range(2):
                resposta = await cliente.post('/postagens', headers=headers,
                                             json={'id': 'abc', 'rede': 'Instagram', 'texto': 'Publicado'})
                assert resposta.status == 201
            assert (cofre / 'Histórico' / 'Postagens.md').read_text(encoding='utf-8').count('postagem:abc') == 1
    asyncio.run(verificar())


def test_perfil_estilo_nao_leva_documentos_nem_filiacao(tmp_path):
    import memoria
    (tmp_path / 'Perfil').mkdir()
    (tmp_path / 'Perfil' / 'Documentos.md').write_text('# Documentos\n\nCNH: ABCDEF\n', encoding='utf-8')
    (tmp_path / 'Perfil' / 'Dados pessoais.md').write_text(
        '# Dados\n\n- Como prefere ser chamado: Deivid\n- Nome da mãe: Fulana\n- Naturalidade: Recife\n',
        encoding='utf-8')
    (tmp_path / 'Perfil' / 'Experiência.md').write_text(
        '# Experiência\n\n- Desenvolvedor backend .NET\n- E-mails secundários:\n> Preencha só o que aceita\n',
        encoding='utf-8')
    texto = memoria.perfil_estilo(tmp_path)
    assert 'Como prefere ser chamado: Deivid' in texto and 'Desenvolvedor backend' in texto
    for proibido in ('ABCDEF', 'Fulana', 'Recife', 'E-mails secundários', 'Preencha'):
        assert proibido not in texto
