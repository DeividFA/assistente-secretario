"""Ponte opcional com autenticação por aparelho e loop isolado do motor."""

import asyncio
import base64
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
import hashlib
import hmac
import io
import ipaddress
import json
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from aiohttp import web
import qrcode
from qrcode.image.pil import PilImage

import diagnostico
import memoria
import registro
import lembretes

APARELHO = web.RequestKey('aparelho', int)
# Um QR mostrado na tela e nunca usado não pode virar chave eterna.
VALIDADE_PAREAMENTO = 600  # segundos

REDES = tuple(ipaddress.ip_network(r) for r in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10'))


def permitido(ip):
    try:
        endereco = ipaddress.ip_address(ip)
        return any(endereco in rede for rede in REDES)
    except ValueError:
        return False


def detectar_ips():
    if sys.platform == 'win32':
        resultado = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command',
             # Só endereços em uso: cabo desconectado deixa o IP fixo em "Tentative".
             'Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred | '
             'Select-Object -ExpandProperty IPAddress'],
            capture_output=True, text=True, timeout=10, creationflags=0x08000000)
        if resultado.returncode:
            raise RuntimeError('Não foi possível detectar os endereços locais.')
        candidatos = resultado.stdout.split()
    else:
        candidatos = [r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    return sorted({ip for ip in candidatos if permitido(ip)})


class Ponte:
    def __init__(self, comando, notificar, banco=registro.BANCO, porta=8765):
        self.comando, self.notificar = comando, notificar
        self.banco, self.porta = banco, porta
        self.thread = None
        self.loop = None
        self.parar_evento = None
        self.ativa = False
        self.ips = []
        self.sockets = {}
        self.limites = defaultdict(deque)
        self.encerrando = threading.Event()
        self.trava = threading.Lock()

    @contextmanager
    def conectar(self):
        con = sqlite3.connect(self.banco, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS aparelhos (
                id INTEGER PRIMARY KEY, nome TEXT, hash TEXT, criado TEXT,
                ultimo_uso TEXT, revogado INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pedidos_celular (
                tarefa INTEGER PRIMARY KEY, aparelho INTEGER, origem TEXT DEFAULT 'celular');
            ''')
            with con:
                yield con
        finally:
            con.close()

    def aparelhos(self):
        with self.conectar() as con:
            return [dict(r) for r in con.execute(
                'SELECT id, nome, criado, ultimo_uso, revogado FROM aparelhos')]

    def parear(self, nome='Celular do Deivid'):
        token = secrets.token_hex(32)
        dados = dict(host_lan=next((ip for ip in self.ips if not ipaddress.ip_address(ip) in REDES[-1]), None),
                     host_tailscale=next((ip for ip in self.ips if ipaddress.ip_address(ip) in REDES[-1]), None),
                     porta=self.porta, token=token)
        imagem = io.BytesIO()
        qrcode.make(json.dumps(dados), image_factory=PilImage).save(imagem, format='PNG')
        with self.conectar() as con:
            con.execute('INSERT INTO aparelhos (nome, hash, criado) VALUES (?, ?, ?)',
                        (nome[:100], hashlib.sha256(token.encode()).hexdigest(), datetime.now().isoformat()))
        return base64.b64encode(imagem.getvalue()).decode('ascii')

    def origem(self, tarefa):
        with self.conectar() as con:
            r = con.execute('SELECT aparelho FROM pedidos_celular WHERE tarefa=?', (tarefa,)).fetchone()
        return r['aparelho'] if r else None

    async def revogar(self, id):
        with self.conectar() as con:
            con.execute('UPDATE aparelhos SET revogado=1 WHERE id=?', (id,))
        for ws, aparelho in list(self.sockets.items()):
            if aparelho == id:
                self.sockets.pop(ws, None)
                await ws.close(code=1008, message=b'Aparelho revogado')

    def criar_app(self):
        @web.middleware
        async def autenticar(request, handler):
            status, aparelho = 500, None
            try:
                cabecalho = request.headers.get('Authorization', '')
                if not cabecalho.startswith('Bearer ') or len(cabecalho) > 256:
                    raise web.HTTPUnauthorized()
                resumo = hashlib.sha256(cabecalho[7:].encode()).hexdigest()
                with self.conectar() as con:
                    limite = datetime.now().timestamp() - VALIDADE_PAREAMENTO
                    for r in con.execute('SELECT id, hash, revogado, criado, ultimo_uso FROM aparelhos'):
                        expirado = (r['ultimo_uso'] is None and
                                    datetime.fromisoformat(r['criado']).timestamp() < limite)
                        if hmac.compare_digest(resumo, r['hash']) and not r['revogado'] and not expirado:
                            aparelho = r['id']
                    if aparelho is None:
                        raise web.HTTPUnauthorized()
                    agora = time.monotonic()
                    usos = self.limites[aparelho]
                    while usos and usos[0] <= agora - 60:
                        usos.popleft()
                    if len(usos) >= 60:
                        raise web.HTTPTooManyRequests(headers={'Retry-After': '60'})
                    usos.append(agora)
                    con.execute('UPDATE aparelhos SET ultimo_uso=? WHERE id=?',
                                (datetime.now().isoformat(), aparelho))
                request[APARELHO] = aparelho
                resposta = await handler(request)
                status = resposta.status
                return resposta
            except web.HTTPException as erro:
                status = erro.status
                raise
            except (ValueError, TypeError, KeyError):
                status = 400
                raise web.HTTPBadRequest()
            finally:
                try:
                    registro.evento('Ponte', json.dumps(dict(metodo=request.method, caminho=request.path,
                                    aparelho=aparelho, status=status)), banco=self.banco)
                except Exception as erro:
                    diagnostico.registrar_bug('ponte', erro, banco=self.banco)

        app = web.Application(middlewares=[autenticar], client_max_size=64 * 1024)
        app.router.add_get('/eventos', self.eventos)
        app.router.add_post('/comando', self.receber_comando)
        app.router.add_post('/memoria/fatos', self.fatos)
        app.router.add_get('/memoria/contexto', self.contexto)
        app.router.add_post('/bugs', self.bug)
        app.router.add_get('/lembretes', self.listar_lembretes)
        app.router.add_post('/lembretes', self.criar_lembrete)
        for metodo, caminho in [('POST', '/gastos'), ('GET', '/gastos'), ('GET', '/apk')]:
            app.router.add_route(metodo, caminho, self.futuro)
        return app

    async def eventos(self, request):
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4096)
        await ws.prepare(request)
        self.sockets[ws] = request[APARELHO]
        try:
            async for mensagem in ws:
                # O WS só entrega eventos; comandos passam pelo limite HTTP.
                await ws.close(code=1008, message=b'Use POST /comando')
        finally:
            self.sockets.pop(ws, None)
        return ws

    async def receber_comando(self, request):
        dados = await request.json()
        texto = dados.get('texto') if isinstance(dados, dict) else None
        if not isinstance(texto, str) or not texto.strip() or len(texto) > 10000:
            raise web.HTTPBadRequest()
        ids = await asyncio.to_thread(self.comando, texto.strip(), request[APARELHO])
        return web.json_response(dict(origem='celular', tarefas=ids), status=202)

    async def fatos(self, request):
        dados = await request.json()
        if not isinstance(dados, dict) or not isinstance(dados.get('fatos_usuario'), list) or not all(
                isinstance(f, str) for f in dados['fatos_usuario']):
            raise web.HTTPBadRequest()
        notas = await asyncio.to_thread(memoria.aprender, {'fatos_usuario': dados['fatos_usuario']})
        return web.json_response(dict(notas=notas))

    async def contexto(self, request):
        texto = await asyncio.to_thread(memoria.contexto, request.query.get('q', '')[:10000])
        return web.json_response(dict(contexto=texto))

    async def bug(self, request):
        dados = await request.json()
        if not isinstance(dados, dict) or not isinstance(dados.get('texto'), str) or not dados['texto'].strip():
            raise web.HTTPBadRequest()
        id = await asyncio.to_thread(diagnostico.registrar_bug, 'celular',
                                    RuntimeError(dados['texto']), banco=self.banco)
        return web.json_response(dict(id=id), status=201 if id is not None else 503)

    async def listar_lembretes(self, request):
        itens = await asyncio.to_thread(lembretes.listar, lembretes.ARQUIVO)
        return web.json_response(dict(lembretes=itens))

    async def criar_lembrete(self, request):
        dados = await request.json()
        if not isinstance(dados, dict) or not isinstance(dados.get('quando'), str):
            raise web.HTTPBadRequest()
        item = await asyncio.to_thread(lembretes.adicionar, dados['quando'], dados.get('texto'),
                                       dados.get('id'), lembretes.ARQUIVO)
        return web.json_response(item, status=201)

    async def futuro(self, request):
        raise web.HTTPNotImplemented()

    async def publicar(self, evento):
        for ws, aparelho in list(self.sockets.items()):
            if evento.get('aparelho') not in (None, aparelho):
                continue
            try:
                await asyncio.wait_for(ws.send_json(evento), timeout=2)
            except Exception:
                self.sockets.pop(ws, None)
                await ws.close()

    def emitir(self, evento):
        if self.ativa and not self.encerrando.is_set() and evento.get('evento') in (
                'mensagem', 'estado', 'fila', 'motores', 'motor', 'ferramenta', 'erro'):
            self.loop.call_soon_threadsafe(lambda: asyncio.create_task(self.publicar(evento)))

    async def servir(self):
        runner = web.AppRunner(self.criar_app(), shutdown_timeout=2)
        try:
            self.ips = await asyncio.to_thread(detectar_ips)
            if not self.ips or not all(permitido(ip) for ip in self.ips):
                raise RuntimeError('Nenhum IP privado ou Tailscale disponível.')
            if self.encerrando.is_set():
                return
            await runner.setup()
            ativos = []
            for ip in self.ips:
                if self.encerrando.is_set():
                    return
                try:  # um adaptador com problema não impede os outros
                    await web.TCPSite(runner, host=ip, port=self.porta).start()
                    ativos.append(ip)
                except OSError as erro:
                    diagnostico.registrar_bug('ponte', erro, banco=self.banco)
            if not ativos:
                raise RuntimeError('Não consegui escutar em nenhum IP local.')
            self.ips = ativos
            self.parar_evento = asyncio.Event()
            if self.encerrando.is_set():
                return
            self.ativa = True
            qr = self.parear()
            self.notificar(evento='ponte', ativa=True, qr=qr, aparelhos=self.aparelhos())
            await self.parar_evento.wait()
        finally:
            self.ativa = False
            for ws in list(self.sockets):
                await ws.close(code=1001)
            await runner.cleanup()
            self.sockets.clear()
            self.parar_evento = None
            self.notificar(evento='ponte', ativa=False, aparelhos=[])

    def iniciar(self):
        def executar():
            try:
                with asyncio.Runner() as runner:
                    self.loop = runner.get_loop()
                    runner.run(self.servir())
            except Exception as erro:
                diagnostico.registrar_bug('ponte', erro, banco=self.banco)
                self.notificar(evento='ponte', ativa=False, erro='Não foi possível ligar a ponte.')
        with self.trava:
            if self.thread and self.thread.is_alive():
                return
            self.encerrando.clear()
            self.thread = threading.Thread(target=executar, daemon=True, name='ponte-celular')
            self.thread.start()

    def desligar(self):
        self.encerrando.set()
        loop, evento = self.loop, self.parar_evento
        if loop and not loop.is_closed() and evento:
            try:
                loop.call_soon_threadsafe(evento.set)
            except RuntimeError:
                pass  # O loop já terminou entre a consulta e o agendamento.
