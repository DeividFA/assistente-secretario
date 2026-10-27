"""Ponte testada com SQLite temporário, sem motor, áudio ou rede externa."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import threading

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ponte


def preparar(tmp_path):
    chamadas = []
    p = ponte.Ponte(lambda texto, aparelho: chamadas.append((texto, aparelho)) or [42],
                    lambda **ev: None, banco=tmp_path / 'teste.db')
    p.ips = ['192.168.1.2', '100.64.1.2']
    qr = p.parear()
    assert base64.b64decode(qr).startswith(b'\x89PNG\r\n\x1a\n')
    # Inserir um token conhecido para testar as rotas sem decodificador de QR.
    token = 'a' * 64
    with p.conectar() as con:
        con.execute('UPDATE aparelhos SET hash=? WHERE id=1',
                    (hashlib.sha256(token.encode()).hexdigest(),))
    return p, {'Authorization': 'Bearer ' + token}, chamadas


def test_bugs_aceita_melhoria_e_rejeita_tipo_invalido(tmp_path):
    async def verificar():
        p, headers, _ = preparar(tmp_path)
        async with TestClient(TestServer(p.criar_app())) as cliente:
            for _ in range(2):
                resposta = await cliente.post('/bugs', headers=headers,
                                             json={'texto': 'Não sabe exportar agenda', 'tipo': 'melhoria'})
                assert resposta.status == 201
            assert (await cliente.post('/bugs', headers=headers,
                                       json={'texto': 'teste', 'tipo': 'outro'})).status == 400
            assert (await cliente.post('/bugs', headers=headers,
                                       json={'texto': 'teste', 'tipo': None})).status == 400
        with p.conectar() as con:
            linhas = list(con.execute('SELECT tipo, ocorrencias FROM bugs'))
            assert len(linhas) == 1
            assert linhas[0]['tipo'] == 'melhoria'
            assert linhas[0]['ocorrencias'] == 2
    asyncio.run(verificar())


def test_autenticacao_revogacao_limite_e_auditoria(tmp_path):
    async def verificar():
        p, headers, chamadas = preparar(tmp_path)
        async with TestClient(TestServer(p.criar_app())) as cliente:
            assert (await cliente.get('/apk')).status == 401
            assert (await cliente.get('/apk', headers={'Authorization': 'Bearer errado'})).status == 401
            for _ in range(60):
                assert (await cliente.get('/apk', headers=headers)).status == 501
            assert (await cliente.get('/apk', headers=headers)).status == 429
            p.limites.clear()
            await p.revogar(1)
            assert (await cliente.get('/apk', headers=headers)).status == 401
        with p.conectar() as con:
            linhas = list(con.execute('SELECT texto FROM eventos'))
            assert len(linhas) == 64
            assert all('a' * 64 not in r['texto'] for r in linhas)
        assert not chamadas
    asyncio.run(verificar())


def test_comando_ws_memoria_bugs_e_validacao(tmp_path, monkeypatch):
    async def verificar():
        p, headers, chamadas = preparar(tmp_path)
        monkeypatch.setattr(ponte.memoria, 'contexto', lambda texto: 'Memória: ' + texto)
        fatos = []
        monkeypatch.setattr(ponte.memoria, 'aprender', lambda dados: fatos.append(dados) or ['nota.md'])
        async with TestClient(TestServer(p.criar_app())) as cliente:
            ws = await cliente.ws_connect('/eventos', headers=headers)
            resposta = await cliente.post('/comando', headers=headers, json={'texto': 'olá', 'origem': 'pc'})
            assert resposta.status == 202
            assert await resposta.json() == {'origem': 'celular', 'tarefas': [42]}
            assert chamadas == [('olá', 1)]
            await p.publicar(dict(evento='mensagem', autor='secretario', texto='Oi', aparelho=1, tarefa=42))
            assert (await ws.receive_json(timeout=2))['texto'] == 'Oi'
            resposta = await cliente.get('/memoria/contexto?q=teste', headers=headers)
            assert await resposta.json() == {'contexto': 'Memória: teste'}
            resposta = await cliente.post('/memoria/fatos', headers=headers, json={'fatos_usuario': ['fato']})
            assert resposta.status == 200
            assert fatos == [{'fatos_usuario': ['fato']}]
            resposta = await cliente.post('/bugs', headers=headers, json={'texto': 'Erro no celular'})
            assert resposta.status == 201
            with p.conectar() as con:
                assert con.execute('SELECT resumo FROM bugs').fetchone()['resumo'] == 'Erro no celular'
            for caminho in ('/comando', '/bugs', '/memoria/fatos'):
                assert (await cliente.post(caminho, headers=headers, json=[])).status == 400
                assert (await cliente.post(caminho, headers={**headers, 'Content-Type': 'application/json'},
                                          data='{')).status == 400
            assert (await cliente.post('/gastos', headers=headers, json={})).status == 400
            await p.revogar(1)
            assert (await ws.receive(timeout=2)).type == WSMsgType.CLOSE
            assert (await cliente.post('/comando', headers=headers, json={'texto': 'x'})).status == 401
    asyncio.run(verificar())


@pytest.mark.parametrize('ip', ['0.0.0.0', '127.0.0.1', '8.8.8.8', '172.32.1.1',
                                   '100.63.255.255', '100.128.0.1', '::', '169.254.1.1'])
def test_recusa_enderecos(ip):
    assert not ponte.permitido(ip)


@pytest.mark.parametrize('ip', ['10.0.0.1', '172.16.0.1', '172.31.255.254',
                                   '192.168.0.1', '100.64.0.1', '100.127.255.254'])
def test_aceita_enderecos(ip):
    assert ponte.permitido(ip)


def test_escuta_somente_ips_detectados_e_cleanup(tmp_path, monkeypatch):
    async def verificar():
        p, _, _ = preparar(tmp_path)
        escutas, eventos = [], []
        monkeypatch.setattr(ponte, 'detectar_ips', lambda: ['192.168.1.2', '100.64.1.2'])
        class Site:
            def __init__(self, runner, host, port):
                escutas.append((host, port))
            async def start(self):
                pass
        monkeypatch.setattr(ponte.web, 'TCPSite', Site)
        def notificar(**ev):
            eventos.append(ev)
            if ev['ativa']:
                p.parar_evento.set()
        p.notificar = notificar
        assert not p.ativa and p.thread is None
        await p.servir()
        assert escutas == [('192.168.1.2', 8765), ('100.64.1.2', 8765)]
        assert eventos[0]['ativa'] and not eventos[-1]['ativa']
        assert not p.ativa
        escutas.clear()
        monkeypatch.setattr(ponte, 'detectar_ips', lambda: ['0.0.0.0'])
        with pytest.raises(RuntimeError):
            await p.servir()
        assert escutas == []
    asyncio.run(verificar())


def test_falha_da_thread_nao_escapa(tmp_path, monkeypatch):
    p, _, _ = preparar(tmp_path)
    eventos, erros = [], []
    p.notificar = lambda **ev: eventos.append(ev)
    monkeypatch.setattr(ponte, 'detectar_ips', lambda: [])
    monkeypatch.setattr(ponte.diagnostico, 'registrar_bug', lambda *a, **kw: erros.append(a))
    p.iniciar()
    p.thread.join(timeout=3)
    assert not p.thread.is_alive() and not p.ativa
    assert erros and eventos[-1]['erro']


def test_origem_persistida_e_sem_fala(tmp_path, monkeypatch):
    import assistente_voz as motor
    import fila
    p, _, _ = preparar(tmp_path)
    assistente = motor.Assistente.__new__(motor.Assistente)
    assistente.ponte = p
    assistente.trava = threading.RLock()
    assistente.motor = 'claude'
    assistente.acordar = threading.Event()
    assistente.emitir_fila = lambda: None
    adicionar = fila.adicionar
    monkeypatch.setattr(motor.fila, 'adicionar', lambda texto, motor: adicionar(texto, motor=motor, banco=p.banco))
    ids = assistente.comando_celular('teste', 1)
    nova = ponte.Ponte(None, None, banco=p.banco)
    assert nova.origem(ids[0]) == 1
    monkeypatch.setattr(motor._contexto, 'trabalho', {'origem': 'celular', 'aparelho': 1}, raising=False)
    # Sem fila de fala no objeto: qualquer tentativa de falar falharia.
    assistente.dizer('resposta', esperar=True)
    eventos = []
    monkeypatch.setattr(motor, '_ponte', type('PonteFalsa', (), {'emitir': lambda self, ev: eventos.append(ev)})())
    monkeypatch.setattr(motor, 'IPC', False)
    motor.emitir(evento='mensagem', autor='secretario', texto='resposta')
    assert eventos[-1]['origem'] == 'celular' and eventos[-1]['aparelho'] == 1


def test_qr_contem_token_e_banco_guarda_so_hash(tmp_path, monkeypatch):
    conteudos = []
    gerar = ponte.qrcode.make
    def capturar(dados, **opcoes):
        conteudos.append(json.loads(dados))
        return gerar(dados, **opcoes)
    monkeypatch.setattr(ponte.qrcode, 'make', capturar)
    p = ponte.Ponte(None, None, banco=tmp_path / 'qr.db')
    p.ips = ['192.168.1.2', '100.64.1.2']
    p.parear('Primeiro celular')
    p.parear('Segundo celular')
    assert conteudos[0]['host_lan'] == '192.168.1.2'
    assert conteudos[0]['host_tailscale'] == '100.64.1.2'
    assert conteudos[0]['porta'] == 8765
    assert len(bytes.fromhex(conteudos[0]['token'])) == 32
    assert conteudos[0]['token'] != conteudos[1]['token']
    with p.conectar() as con:
        linhas = list(con.execute('SELECT * FROM aparelhos ORDER BY id'))
    for dados, linha in zip(conteudos, linhas):
        assert linha['hash'] == hashlib.sha256(dados['token'].encode()).hexdigest()
        assert dados['token'] not in json.dumps(dict(linha))


def test_desligar_durante_deteccao_nao_abre_porta(tmp_path, monkeypatch):
    p, _, _ = preparar(tmp_path)
    entrou, liberar = threading.Event(), threading.Event()
    eventos, escutas = [], []
    def detectar():
        entrou.set()
        assert liberar.wait(timeout=3)
        return ['192.168.1.2']
    monkeypatch.setattr(ponte, 'detectar_ips', detectar)
    monkeypatch.setattr(ponte.web, 'TCPSite', lambda *a, **kw: escutas.append(kw))
    p.notificar = lambda **ev: eventos.append(ev)
    p.iniciar()
    try:
        assert entrou.wait(timeout=3)
        assert p.loop is not None and p.thread.ident != threading.get_ident()
        p.desligar()
    finally:
        liberar.set()
        p.thread.join(timeout=3)
    assert not p.thread.is_alive() and not p.ativa
    assert not escutas and not any(ev['ativa'] for ev in eventos)


def test_limite_expira_e_e_por_aparelho(tmp_path, monkeypatch):
    async def verificar():
        p, headers, _ = preparar(tmp_path)
        agora = [1000.0]
        # Não alterar o relógio do módulo asyncio, compartilhado com time.
        from types import SimpleNamespace
        monkeypatch.setattr(ponte, 'time', SimpleNamespace(monotonic=lambda: agora[0]))
        p.parear('Outro celular')
        outro = 'b' * 64
        with p.conectar() as con:
            con.execute('UPDATE aparelhos SET hash=? WHERE id=2',
                        (hashlib.sha256(outro.encode()).hexdigest(),))
        async with TestClient(TestServer(p.criar_app())) as cliente:
            for _ in range(60):
                assert (await cliente.get('/apk', headers=headers)).status == 501
            assert (await cliente.get('/apk', headers=headers)).status == 429
            assert (await cliente.get('/apk', headers={'Authorization': 'Bearer ' + outro})).status == 501
            agora[0] += 60
            assert (await cliente.get('/apk', headers=headers)).status == 501
    asyncio.run(verificar())


def test_ws_resposta_so_para_aparelho_de_origem(tmp_path):
    async def verificar():
        p, headers, _ = preparar(tmp_path)
        p.parear('Outro celular')
        outro = 'b' * 64
        with p.conectar() as con:
            con.execute('UPDATE aparelhos SET hash=? WHERE id=2',
                        (hashlib.sha256(outro.encode()).hexdigest(),))
        async with TestClient(TestServer(p.criar_app())) as cliente:
            primeiro = await cliente.ws_connect('/eventos', headers=headers)
            segundo = await cliente.ws_connect('/eventos', headers={'Authorization': 'Bearer ' + outro})
            await p.publicar(dict(evento='mensagem', texto='privada', aparelho=1))
            await p.publicar(dict(evento='estado', estado='ouvindo'))
            assert (await primeiro.receive_json(timeout=2))['texto'] == 'privada'
            assert (await primeiro.receive_json(timeout=2))['evento'] == 'estado'
            assert (await segundo.receive_json(timeout=2))['evento'] == 'estado'
            await primeiro.close()
            await segundo.close()
    asyncio.run(verificar())


def test_config_padrao_desligada():
    import config
    assert config.PADROES['ponte_ativa'] is False


def test_autenticacao_compara_hash_com_tempo_constante(tmp_path, monkeypatch):
    async def verificar():
        p, headers, _ = preparar(tmp_path)
        comparacoes = []
        comparar = ponte.hmac.compare_digest
        def capturar(a, b):
            comparacoes.append((a, b))
            return comparar(a, b)
        monkeypatch.setattr(ponte.hmac, 'compare_digest', capturar)
        async with TestClient(TestServer(p.criar_app())) as cliente:
            assert (await cliente.get('/apk', headers=headers)).status == 501
        esperado = hashlib.sha256(('a' * 64).encode()).hexdigest()
        assert comparacoes == [(esperado, esperado)]
    asyncio.run(verificar())


def test_falha_em_um_ip_mantem_os_outros_e_fecha_ao_desligar(tmp_path, monkeypatch):
    async def verificar():
        p, _, _ = preparar(tmp_path)
        eventos, abertos = [], []
        p.notificar = lambda **ev: eventos.append(ev)
        monkeypatch.setattr(ponte, 'detectar_ips', lambda: ['192.168.1.2', '100.64.1.2'])
        class Site:
            def __init__(self, runner, host, port):
                self.runner, self.host = runner, host
            async def start(self):
                if self.host.startswith('100.'):
                    raise OSError('Porta ocupada')
                self.runner._reg_site(self)
                abertos.append(self.host)
            async def stop(self):
                abertos.remove(self.host)
                self.runner._unreg_site(self)
        monkeypatch.setattr(ponte.web, 'TCPSite', Site)
        # Um adaptador com problema (ex.: IP fixo de cabo desconectado) não derruba a ponte.
        tarefa = asyncio.create_task(p.servir())
        for _ in range(100):
            if p.ativa:
                break
            await asyncio.sleep(0.02)
        assert p.ativa and abertos == ['192.168.1.2'] and p.ips == ['192.168.1.2']
        p.parar_evento.set()
        await asyncio.wait_for(tarefa, 5)
        assert not abertos and not p.ativa
        assert eventos[-1]['ativa'] is False
    asyncio.run(verificar())


def test_nenhum_ip_disponivel_desiste(tmp_path, monkeypatch):
    async def verificar():
        p, _, _ = preparar(tmp_path)
        p.notificar = lambda **ev: None
        monkeypatch.setattr(ponte, 'detectar_ips', lambda: ['192.168.1.2'])

        class Site:
            def __init__(self, runner, host, port):
                pass

            async def start(self):
                raise OSError('Porta ocupada')
        monkeypatch.setattr(ponte.web, 'TCPSite', Site)
        with pytest.raises(RuntimeError, match='nenhum IP'):
            await asyncio.wait_for(p.servir(), 5)
        assert not p.ativa
    asyncio.run(verificar())


def test_qr_nao_usado_expira(tmp_path, monkeypatch):
    import asyncio, hashlib
    from datetime import datetime, timedelta
    from aiohttp.test_utils import TestClient, TestServer
    import ponte as modulo
    p = modulo.Ponte(lambda texto, aparelho: [], lambda **ev: None, banco=tmp_path / "t.db")
    token = "a" * 64
    antigo = (datetime.now() - timedelta(seconds=modulo.VALIDADE_PAREAMENTO + 5)).isoformat()
    with p.conectar() as con:
        con.execute("INSERT INTO aparelhos (nome, hash, criado) VALUES ('x', ?, ?)",
                    (hashlib.sha256(token.encode()).hexdigest(), antigo))

    async def rodar():
        async with TestClient(TestServer(p.criar_app())) as cliente:
            r = await cliente.get("/memoria/contexto?q=x", headers={"Authorization": "Bearer " + token})
            return r.status
    assert asyncio.run(rodar()) == 401


def test_lembretes_autenticacao_validacao_e_repeticao(tmp_path, monkeypatch):
    async def verificar():
        p, headers, _ = preparar(tmp_path)
        arquivo = tmp_path / 'lembretes.json'
        monkeypatch.setattr(ponte.lembretes, 'ARQUIVO', arquivo)
        async with TestClient(TestServer(p.criar_app())) as cliente:
            assert (await cliente.get('/lembretes')).status == 401
            assert (await cliente.post('/lembretes', json={})).status == 401
            resposta = await cliente.get('/lembretes', headers=headers)
            assert await resposta.json() == {'lembretes': []}
            item = dict(id='celular-1', quando='2026-11-02T15:00', texto='Consulta')
            for _ in range(2):
                resposta = await cliente.post('/lembretes', headers=headers, json=item)
                assert resposta.status == 201
                assert (await resposta.json())['feito'] is False
            # O formato continua compatível com o leitor de notificações do PC.
            itens = json.loads(arquivo.read_text(encoding='utf-8'))
            assert itens == [dict(item, feito=False)]
            itens[0]['feito'] = True
            arquivo.write_text(json.dumps(itens), encoding='utf-8')
            await cliente.post('/lembretes', headers=headers, json=item)
            resposta = await cliente.get('/lembretes', headers=headers)
            assert await resposta.json() == {'lembretes': itens}
            for invalido in ([], {}, dict(item, quando='amanhã'), dict(item, quando='2026-02-30T15:00'),
                             dict(item, texto=''), dict(item, id=23), dict(item, texto='Outro')):
                assert (await cliente.post('/lembretes', headers=headers, json=invalido)).status == 400
            assert json.loads(arquivo.read_text(encoding='utf-8')) == itens
            await p.revogar(1)
            assert (await cliente.get('/lembretes', headers=headers)).status == 401
    asyncio.run(verificar())


def test_lembretes_compartilham_formato_mcp(tmp_path):
    arquivo = tmp_path / 'lembretes.json'
    arquivo.write_text(json.dumps([dict(quando='2026-11-01T09:00', texto='PC', feito=False)]), encoding='utf-8')
    ponte.lembretes.adicionar('2026-11-02T10:00', 'Celular', 'id-1', arquivo)
    itens = ponte.lembretes.listar(arquivo)
    assert len(itens) == 2
    assert itens[0]['texto'] == 'PC'
    assert itens[1]['texto'] == 'Celular'
