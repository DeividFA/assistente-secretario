"""Motor do secretário: ouve o microfone, entende comandos e executa via Claude Code.

Só age quando ouve a palavra de ativação "secretário" (ou durante alguns segundos
depois de uma resposta, para ele responder perguntas como "Posso enviar?").

Modos:
  python assistente_voz.py          terminal (texto no console)
  python assistente_voz.py --ipc    controlado pelo app Electron: emite eventos JSON
                                    no stdout e recebe comandos JSON no stdin

Comandos falados de controle (depois de "secretário"):
  "cancela" / "para"   interrompe a tarefa   ·  "nova conversa"  começa outra sessão
  "desligar"           encerra o motor   ·  "reinicia" / "reinicia tudo"  reinicia motor/app

Comandos do app (stdin, uma linha JSON cada):
  {"cmd":"texto","texto":"..."}  {"cmd":"cancelar"}  {"cmd":"mudo","valor":true}
  {"cmd":"silencio","valor":true}  {"cmd":"sessao","id":"..."|null}
  {"cmd":"ouvir_agora"}  {"cmd":"sair"}
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import fila
import backup
import registro
import diagnostico
import reparo
import agente_local
import motores_cli
import provedores
import config
import dispositivos
import vozes
import memoria
import extrator
import vocabulario
from vocabulario import ativacao_tolerante

from comum import BASE, Microfone, bip, falar, normalizar, texto_para_fala, transcrever
from comum import aquecer_voz, interromper_fala

IPC = "--ipc" in sys.argv
ATIVACAO = re.compile(r"\bsecret[aá]ri[oa]\b[\s,.!?:;-]*", re.I)
JANELA_CONVERSA = 15  # segundos após uma resposta em que dá para responder sem dizer "secretário"
LOG = BASE / "log_voz.txt"
PROMPT_VOZ = (BASE / "voz_prompt.md").read_text(encoding="utf-8") + "\nSiga as preferências de Preferências/Estilo.md do cofre."
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
# Motor do cérebro escolhido entre os nomes do registro de provedores.
ARQ_MOTOR = BASE / "motor.txt"
TROCA_MOTOR = re.compile(r"^(?:usa|usar|use|muda|mudar|troca|trocar|volta|voltar|liga|ligar)"
                         r"\s+(?:(?:o|a|para|pro|pra|motor)\s+)*(claude|cloud|codex|gemini-cli|"
                         r"gemini|gemini cli|jemini|grok|groque|gpt|chat gpt|deepseek|mistral|"
                         r"openrouter|gemma|qwen)[.!?]*$")

NOMES_FERRAMENTAS = {
    "mcp__playwright__": "navegador",
    "mcp__sentidos__captura_tela": "olhando a tela",
    "mcp__sentidos__foto_camera": "câmera",
    "mcp__sentidos__": "controlando o computador",
    "PowerShell": "PowerShell",
    "Bash": "terminal",
    "Read": "lendo arquivo",
    "Write": "escrevendo arquivo",
    "Edit": "editando arquivo",
    "Grep": "pesquisando na memória",
    "Glob": "procurando arquivos",
    "WebSearch": "pesquisando na web",
    "WebFetch": "lendo página",
    "Skill": "carregando habilidade",
    "ToolSearch": "preparando ferramentas",
}

if IPC:
    sys.stdout.reconfigure(encoding="utf-8")
_saida = threading.Lock()
_registro = threading.Lock()
_contexto = threading.local()
_ponte = None


def emitir(**evento):
    if evento.get('evento') in ('mensagem', 'ferramenta', 'erro'):
        evento.setdefault('tarefa', getattr(_contexto, 'id', None))
    trabalho = getattr(_contexto, 'trabalho', {})
    if trabalho.get('motor') and evento.get('evento') in ('mensagem', 'ferramenta', 'erro'):
        evento.setdefault('motor', trabalho['motor'])
    if trabalho.get('origem') == 'celular' and evento.get('evento') in ('mensagem', 'ferramenta', 'erro'):
        evento.setdefault('origem', 'celular')
        evento.setdefault('aparelho', trabalho['aparelho'])
    if _ponte is not None:
        try:
            _ponte.emitir(evento.copy())
        except Exception as erro:
            diagnostico.registrar_bug('ponte', erro)
    if IPC:
        with _saida:
            sys.stdout.write(json.dumps(evento, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def registrar(quem, texto):
    from registro import evento
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {quem}: {texto}"
    if not IPC:
        print(linha, flush=True)
    with _registro:
        if LOG.exists() and LOG.stat().st_size > 1024 * 1024:
            LOG.replace(LOG.with_name("log_voz.1.txt"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    try:
        evento(quem, texto)
    except Exception as e:  # o log no banco nunca pode derrubar o motor
        diagnostico.registrar_bug("motor", e, e.__traceback__,
                                 {"motor": getattr(_contexto, "trabalho", {}).get("motor", "")})
        print(f"registro SQLite falhou: {e}", file=sys.stderr)


def nome_ferramenta(nome):
    for prefixo, rotulo in NOMES_FERRAMENTAS.items():
        if nome.startswith(prefixo):
            return rotulo
    return nome


LOCAIS = {"gemma"}  # motores que rodam no próprio PC


def escolher_motor(preferido, ocupacao, disponiveis, ordem, vagas):
    """Escolhe sem consultar serviços nem alterar os argumentos recebidos."""
    # Quem escolhe o Gemma quer que nada saia do PC: espera a vaga em vez de ir para a nuvem.
    candidatos = [preferido] if preferido in LOCAIS else [preferido, *ordem]
    for motor in dict.fromkeys(candidatos):
        if motor not in disponiveis:
            continue
        tipo = provedores.MOTORES.get(motor, {}).get('tipo')
        limite = vagas.get(motor, vagas.get('api', 0) if tipo == 'api' else 0)
        if motor == 'gemma':
            limite = min(limite, 1)
        if ocupacao.get(motor, 0) < limite:
            return motor
    return None


class Assistente:
    def __init__(self):
        self.mic = Microfone(abrir=False)
        self.ditado_pendente = False
        self.ditando = False
        self.config_mic = config.carregar()
        self.config_mic['ponte_ativa'] = False
        self.ponte = None
        self.apps_mic = []
        self.consultar_mic_apos = 0.0
        self.comando_mic_ate = 0.0
        self.demanda_ativa = False
        self.ultimo_estado_mic = None
        self.trabalhos = {}
        self.trava = threading.RLock()
        self.acordar = threading.Event()
        self.falas = queue.Queue()
        self.falando = False
        self.sessao = None
        self.silencio = False  # não falar as respostas (equivalente ao "ensurdecer" do Discord)
        self.conversa_ate = 0.0
        self.ativo = True
        self.motor = ARQ_MOTOR.read_text(encoding="utf-8").strip() if ARQ_MOTOR.exists() else "claude"
        if self.motor not in provedores.MOTORES:
            self.motor = "claude"
        self.historicos_api = {}
        self.sessoes_cli = {}
        self.pendentes_api = {}
        self.banco_falho = False
        self.restauro_pendente = None  # nome do backup aguardando o "sim"
        self.voz_pendente = None
        self.downloads_voz = set()
        self.reparo_pendente = None
        self.reparando = False
        self.reinicio_reparo = False
        try:
            import ponte
            self.ponte = ponte.Ponte(self.comando_celular, self.notificar_ponte)
            global _ponte
            _ponte = self.ponte
        except Exception as erro:
            diagnostico.registrar_bug('ponte', erro)

    @property
    def ocupado(self):
        with self.trava:
            return bool(self.trabalhos)

    def emitir_fila(self):
        tarefas = fila.listar()
        if getattr(self, 'ponte', None) is not None:
            try:
                with self.ponte.conectar() as con:
                    origens = {r['tarefa']: r['aparelho'] for r in con.execute(
                        'SELECT tarefa, aparelho FROM pedidos_celular')}
                for tarefa in tarefas:
                    if tarefa['id'] in origens:
                        tarefa.update(origem='celular', aparelho=origens[tarefa['id']])
            except Exception as erro:
                diagnostico.registrar_bug('ponte', erro)
        emitir(evento="fila", tarefas=tarefas)

    def preparar_memoria(self):
        try:
            memoria.preparar_cofre()
            memoria.indexar()
        except Exception as erro:
            registrar("ERRO", f"Inicialização da memória: {erro}")

    def aprender_resposta(self, comando, resposta):
        def aprender():
            try:
                memoria.registrar_diario(comando, resposta)
                conhecimento = extrator.extrair(comando, resposta)
                notas = memoria.aprender(conhecimento)
                if notas:
                    emitir(evento="memoria", notas=notas)
            except Exception as erro:
                registrar("ERRO", f"Aprendizado da memória: {erro}")

        threading.Thread(target=aprender, daemon=True).start()

    def despachar(self):
        while self.ativo:
            self.acordar.clear()
            try:
                with self.trava:
                    pendentes = [] if self.reparando else [t for t in fila.listar() if t['status'] == 'pendente']
                    ocupacao = {}
                    for trabalho in self.trabalhos.values():
                        nome = trabalho['motor']
                        ocupacao[nome] = ocupacao.get(nome, 0) + 1
                    ordem = self.config_mic['motores_paralelos']
                    disponiveis = {nome for nome in dict.fromkeys([self.motor, *ordem])
                                   if pendentes and provedores.disponivel(nome)[0]}
                    for pendente in pendentes:
                        # Uma derivação paralela não implica dependência da sessão.
                        # Pedidos explicitamente dependentes conservam o --resume/fork.
                        permitidos = ({'claude'} & disponiveis
                                      if pendente.get('depende_sessao') else disponiveis)
                        motor = escolher_motor(self.motor, ocupacao, permitidos, ordem,
                                               self.config_mic['vagas'])
                        if motor is not None:
                            # Reserva o pedido escolhido e seu motor na mesma transação.
                            con = fila._conectar(fila.BANCO)
                            try:
                                with con:
                                    inicio = datetime.now().isoformat()
                                    reservado = con.execute(
                                        "UPDATE fila SET status = 'rodando', inicio = ?, motor = ? "
                                        "WHERE id = ? AND status = 'pendente'",
                                        (inicio, motor, pendente['id'])).rowcount
                                tarefa = dict(pendente, motor=motor, status='rodando', inicio=inicio) if reservado else None
                            finally:
                                con.close()
                            if tarefa:
                                if getattr(self, 'ponte', None) is not None:
                                    aparelho = self.ponte.origem(tarefa['id'])
                                    if aparelho is not None:
                                        tarefa.update(origem='celular', aparelho=aparelho)
                                tarefa.update(proc=None, cancelado=False,
                                              derivada=bool(self.trabalhos), sessao=self.sessao)
                                if self.trabalhos:
                                    tarefa['simultanea'] = True
                                    for outra in self.trabalhos.values():
                                        outra['simultanea'] = True
                                self.trabalhos[tarefa['id']] = tarefa
                                self.emitir_fila()
                                threading.Thread(target=self.trabalhar, args=(tarefa,), daemon=True).start()
                                ocupacao[motor] = ocupacao.get(motor, 0) + 1
            except Exception as e:
                diagnostico.registrar_bug("motor", e, e.__traceback__,
                                         {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                registrar('ERRO', f'Executor da fila: {e}')
            self.acordar.wait(0.5)

    def trabalhar(self, trabalho):
        _contexto.id = trabalho['id']
        _contexto.trabalho = trabalho
        trabalho.update(status_final='erro', resposta_final='')
        try:
            if not trabalho['cancelado']:
                self.tarefa(trabalho['comando'])
        except Exception as e:
            diagnostico.registrar_bug("motor", e, e.__traceback__,
                                     {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
            registrar('ERRO', str(e))
            trabalho['resposta_final'] = str(e)
            emitir(evento='erro', texto=str(e))
        finally:
            with self.trava:
                try:
                    fila.concluir(trabalho['id'], 'cancelada' if trabalho['cancelado']
                                  else trabalho['status_final'], trabalho['resposta_final'])
                finally:
                    self.trabalhos.pop(trabalho['id'], None)
                    self.acordar.set()
            self.emitir_fila()
            self.estado_ocioso()

    def falar_fila(self):
        while self.ativo:
            texto, tarefa, pronto = self.falas.get()
            try:
                if tarefa is None or not tarefa.get('cancelado', False):
                    self._dizer(texto, tarefa.get('voz_amostra') if tarefa else None)
                    if tarefa is not None and 'voz_amostra' not in tarefa:
                        self.conversa_ate = time.monotonic() + JANELA_CONVERSA
            except Exception as e:
                diagnostico.registrar_bug("motor", e, e.__traceback__,
                                         {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                registrar('ERRO', f'Fala: {e}')
            finally:
                pronto.set()
                self.falas.task_done()

    def dizer(self, texto, esperar=False):
        trabalho = getattr(_contexto, 'trabalho', None)
        if trabalho and trabalho.get('origem') == 'celular':
            return
        if trabalho:
            with self.trava:
                if trabalho.get('simultanea'):
                    texto = f"Sobre {trabalho['comando'][:60]}: {texto}"
        pronto = threading.Event()
        self.falas.put((texto, trabalho, pronto))
        if esperar:
            pronto.wait()

    def estado(self, estado):
        emitir(evento="estado", estado=estado)

    def estado_ocioso(self):
        self.estado('falando' if self.falando else 'pensando' if self.ocupado
                    else 'mudo' if self.mic.pausado else 'ouvindo' if self.mic.stream is not None
                    else 'microfone_indisponivel' if self.mic.erro else 'liberado')

    def mensagem(self, autor, texto):
        registrar({"voce": "Você", "secretario": "Secretário"}.get(autor, autor), texto)
        emitir(evento="mensagem", autor=autor, texto=texto)

    def _dizer(self, texto, voz=None):
        """Fala com o microfone mudo, para não ouvir a própria voz."""
        self.consultar_microfone()
        if self.apps_mic:
            emitir(evento="resposta_silenciosa", texto=texto)
            return
        if self.silencio:
            return
        self.falando = True
        self.estado("falando")
        self.mic.mudo = True
        try:
            falar(texto_para_fala(texto), voz=voz)
        finally:
            time.sleep(0.2)
            self.mic.limpar()
            self.mic.mudo = False
            self.falando = False
            if self.voz_pendente:
                self.conversa_ate = time.monotonic() + JANELA_CONVERSA
            self.estado_ocioso()

    def emitir_motores(self):
        emitir(evento="motores", lista=provedores.listar(), atual=self.motor)

    def emitir_vozes(self):
        emitir(evento="vozes", lista=vozes.listar(), atual=config.carregar().get("voz", "windows"))
        aquecer_voz()  # chamado depois de cada troca de voz; só carrega se for Piper

    def baixar_voz(self, id, ativar=False):
        with self.trava:
            if id in self.downloads_voz:
                return
            self.downloads_voz.add(id)

        def baixar():
            ultimo = -5

            def progresso(feito, total):
                nonlocal ultimo
                percentual = min(95, int(feito * 100 / total)) if total else 0
                if percentual >= ultimo + 5:
                    ultimo = percentual
                    emitir(evento="download_voz", id=id, feito=feito, total=total)

            try:
                vozes.baixar(id, progresso)
                if ativar:
                    vozes.usar(id)
                emitir(evento="download_voz", id=id, feito=1, total=1)
            except Exception as erro:
                diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                         {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                emitir(evento="erro", id=id, texto=f"Não consegui baixar a voz: {erro}")
            finally:
                with self.trava:
                    self.downloads_voz.discard(id)
                self.emitir_vozes()

        threading.Thread(target=baixar, daemon=True).start()

    def amostra_voz(self, id):
        vozes.obter(id)
        with self.trava:
            if self.silencio:
                return
        # Usa a mesma fila e proteção do microfone das respostas.
        self.falas.put(("Olá, Deivid. Esta é a minha nova voz.", {"voz_amostra": id}, threading.Event()))

    def trocar_motor(self, motor):
        if motor not in provedores.MOTORES:
            self.dizer("Motor desconhecido.")
            return
        disponivel, motivo = provedores.disponivel(motor)
        if not disponivel:
            self.mensagem("sistema", motivo)
            self.dizer(motivo)
            self.emitir_motores()
            return
        with self.trava:
            ARQ_MOTOR.write_text(motor, encoding="utf-8")
            self.motor = motor
        nome = provedores.MOTORES[motor]["rotulo"]
        self.emitir_motores()
        self.mensagem("sistema", f"Motor: {nome}.")
        self.dizer(f"Ok, agora estou usando o {nome}.")

    def tarefa_provedor(self, comando, motor, ctx):
        from registro import inicio_tarefa, fim_tarefa
        trabalho = _contexto.trabalho
        tarefa_id = inicio_tarefa(comando, motor)
        status, resposta, ferramentas = "erro", "", []
        try:
            if provedores.MOTORES[motor]["tipo"] == "cli":
                def ao_evento(evento):
                    if evento["tipo"] == "processo":
                        with self.trava:
                            trabalho['proc'] = evento['proc']
                            if trabalho['cancelado'] or not self.ativo:
                                raise RuntimeError("Tarefa cancelada.")
                    elif evento["tipo"] == "ferramenta":
                        ferramentas.append(evento['nome'])
                        emitir(evento="ferramenta", nome=nome_ferramenta(evento['nome']))
                resultado = motores_cli.executar(
                    motor, ctx + "\n\nPedido: " + comando if ctx else comando,
                    ao_evento, sessao=None if trabalho['derivada'] else self.sessoes_cli.get(motor),
                    prompt_sistema=PROMPT_VOZ)
                if not trabalho['derivada'] and not trabalho['cancelado']:
                    self.sessoes_cli[motor] = resultado['sessao']
                resposta = resultado['resposta']
            else:
                def chamar(mensagens, imagens=None):
                    if trabalho['cancelado'] or not self.ativo:
                        raise RuntimeError("Tarefa cancelada.")
                    mensagens = [dict(m) for m in mensagens]
                    mensagens[0]['content'] = PROMPT_VOZ + '\n\n' + mensagens[0]['content']
                    saida = provedores.chamar_api(motor, mensagens, json=True, imagens=imagens)
                    if trabalho['cancelado'] or not self.ativo:
                        raise RuntimeError("Tarefa cancelada.")
                    return saida
                with self.trava:
                    historico = list(self.historicos_api.get(motor, []))
                    pendente = self.pendentes_api.pop(motor, None)
                if pendente and re.match(r"^(sim|pode|confirmo)\b", normalizar(comando)):
                    resultado = agente_local.confirmar(pendente)
                else:
                    resultado = agente_local.executar(comando, historico, memoria=ctx, chamar=chamar)
                if trabalho['cancelado']:
                    return
                ferramentas = resultado['passos']
                for nome in ferramentas:
                    emitir(evento="ferramenta", nome=nome_ferramenta(nome))
                resposta = resultado['texto']
                with self.trava:
                    if resultado.get('pendente'):
                        self.pendentes_api[motor] = resultado['pendente']
                    historico.extend([{"role": "user", "content": comando},
                                      {"role": "assistant", "content": resposta}])
                    self.historicos_api[motor] = historico[-20:]
            if trabalho['cancelado']:
                return
            status = "erro" if resposta == agente_local.DESISTENCIA else "ok"
            self.mensagem("secretario", resposta)
            self.dizer(resposta)
            self.aprender_resposta(comando, resposta)
            self.conversa_ate = time.monotonic() + JANELA_CONVERSA
        finally:
            trabalho['proc'] = None
            trabalho.update(status_final='concluida' if status == 'ok' else 'erro',
                            resposta_final=resposta)
            fim_tarefa(tarefa_id, 'cancelada' if trabalho['cancelado'] else status,
                       resposta, ferramentas)

    def tarefa(self, comando):
        from registro import inicio_tarefa, fim_tarefa
        self.estado("pensando")
        motor = _contexto.trabalho['motor']
        if motor not in provedores.MOTORES:
            raise ValueError("Motor desconhecido.")
        ctx = ""
        try:
            ctx = memoria.contexto(comando)
        except Exception as e:
            diagnostico.registrar_bug("motor", e, e.__traceback__,
                                     {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
            registrar("ERRO", f"Contexto de memória: {e}")
        if motor != "claude":
            self.tarefa_provedor(comando, motor, ctx)
            return
        pedido = ctx + "\n\nPedido: " + comando if ctx else comando
        tarefa_id = inicio_tarefa(comando, "claude")
        status = "erro"
        ferramentas = []
        nomes_ferramentas = {}
        resposta = None
        erro = ""
        try:
            args = motores_cli.resolver_executavel(CLAUDE) + ["-p", pedido, "--output-format", "stream-json", "--verbose",
                    "--permission-mode", "auto", "--append-system-prompt", PROMPT_VOZ]
            trabalho = _contexto.trabalho
            if trabalho['sessao']:
                args += ['--resume', trabalho['sessao']]
                if trabalho['derivada']:
                    args += ['--fork-session']
            # stdin=DEVNULL: senão o claude -p fica esperando ler o canal de comandos do app.
            with self.trava:
                if trabalho['cancelado'] or not self.ativo:
                    return
                trabalho['proc'] = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, cwd=str(Path.home()), text=True,
                    encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
            resposta = None
            erro = ''
            for linha in _contexto.trabalho['proc'].stdout:
                try:
                    ev = json.loads(linha)
                except json.JSONDecodeError:
                    erro = (erro + linha)[-2000:]
                    continue
                if not trabalho["derivada"] and ev.get("session_id") and ev["session_id"] != self.sessao:
                    with self.trava:
                        self.sessao = ev["session_id"]
                        emitir(evento="sessao", id=self.sessao)
                if ev.get("type") == "assistant":
                    for bloco in ev.get("message", {}).get("content", []):
                        if bloco.get("type") == "tool_use":
                            nome = bloco.get("name", "")
                            nomes_ferramentas[bloco.get("id")] = nome
                            if nome and nome not in ferramentas:
                                ferramentas.append(nome)
                            emitir(evento="ferramenta", nome=nome_ferramenta(bloco.get("name", "")))
                elif ev.get("type") == "user":
                    for bloco in ev.get("message", {}).get("content", []):
                        if isinstance(bloco, dict) and bloco.get("type") == "tool_result":
                            nome = nomes_ferramentas.get(bloco.get('tool_use_id'), 'desconhecida')
                            registro.evento('Ferramenta', nome + ':' + ('erro' if bloco.get('is_error') else 'ok'))
                elif ev.get("type") == "result":
                    resposta = ev.get("result")
                    status = "erro" if ev.get("is_error") else "ok"
            _contexto.trabalho['proc'].wait()
            if _contexto.trabalho['cancelado']:
                return
            if _contexto.trabalho['proc'].returncode:
                status = "erro"
            if resposta is None:
                registrar("ERRO", erro.strip()[-500:])
                emitir(evento="erro", texto=erro.strip()[-500:] or "O Claude não respondeu.")
                self.dizer("Deu um erro ao executar. Os detalhes estão na tela.")
                return
            resposta = resposta or "Pronto."
            self.mensagem("secretario", resposta)
            self.dizer(resposta)
            self.aprender_resposta(comando, resposta)
            self.conversa_ate = time.monotonic() + JANELA_CONVERSA
        except Exception as e:
            diagnostico.registrar_bug("motor", e, e.__traceback__,
                                     {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
            erro = str(e)
            status = "erro"
            raise
        finally:
            proc = _contexto.trabalho['proc']
            if proc and proc.poll() is None:
                subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
            _contexto.trabalho['proc'] = None
            _contexto.trabalho.update(status_final='concluida' if status == 'ok' else 'erro',
                                     resposta_final=resposta if resposta is not None else erro.strip()[-2000:])
            fim_tarefa(tarefa_id, "cancelada" if _contexto.trabalho['cancelado'] else status,
                       resposta if resposta is not None else erro.strip()[-2000:], ferramentas)

    def cancelar(self, id=None, tudo=False):
        interromper_fala()
        with self.trava:
            ids = ([t['id'] for t in fila.listar()] if tudo else
                   [id] if id is not None else list(self.trabalhos)[-1:])
            canceladas = []
            for tarefa_id in ids:
                if fila.cancelar(tarefa_id):
                    canceladas.append(tarefa_id)
                    trabalho = self.trabalhos.get(tarefa_id)
                    if trabalho:
                        trabalho['cancelado'] = True
                        proc = trabalho['proc']
                        if proc and proc.poll() is None:
                            subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'],
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                    registrar('Sistema', 'Tarefa cancelada.')
                    emitir(evento='mensagem', autor='sistema', texto='Tarefa cancelada.', tarefa=tarefa_id)
            self.emitir_fila()
            self.acordar.set()
        self.dizer('Tarefa cancelada.' if canceladas else 'Não tem nada rodando.')

    def executar(self, comando):
        """Trata comandos de controle ou dispara uma tarefa."""
        c = normalizar(comando)
        if self.reparo_pendente and c.startswith('orientacao:'):
            id, _ = self.reparo_pendente
            self.pedir_reparo(id, comando.split(':', 1)[1].strip())
            return
        if self.reparo_pendente and re.match(r"^(?:sim|pode|confirmo|nao)(?:[.!?,]|$)", c):
            id, diretriz = self.reparo_pendente
            self.reparo_pendente = None
            if c.startswith(('sim', 'pode', 'confirmo')):
                if ',' in comando:
                    diretriz = comando.split(',', 1)[1].strip()
                self.iniciar_reparo(id, diretriz)
            return
        if self.reinicio_reparo and c in ('sim', 'pode', 'confirmo'):
            self.reinicio_reparo = False
            self.dizer("Reiniciando.", esperar=True)
            emitir(evento='reiniciar', completo=False)
            return
        if c.rstrip('?!.') == 'o que deu errado':
            self.emitir_bugs()
            self.dizer('; '.join(b['resumo'] for b in registro.listar_bugs()[:3]) or 'Nenhum problema registrado.')
            return
        if c.startswith('anota uma melhoria:'):
            diagnostico.registrar_bug('pedido', ValueError(comando.split(':', 1)[1].strip()), tipo='melhoria')
            self.emitir_bugs()
            self.dizer('Melhoria anotada.')
            return
        if c.startswith('corrige o problema'):
            numero = re.search(r'\d+', c)
            bugs = [b for b in registro.listar_bugs() if b['estado'] not in ('corrigido', 'ignorado')]
            id = int(numero.group()) if numero else bugs[0]['id'] if bugs else None
            if id is not None:
                self.pedir_reparo(id)
            return
        self.reparo_pendente = None
        self.reinicio_reparo = False
        if self.restauro_pendente:
            nome, self.restauro_pendente = self.restauro_pendente, None
            if re.match(r"(sim|pode|confirmo|restaura)\b", c):
                self.restaurar(nome)
                return
            if self.banco_falho:
                self.dizer("Ok, não restaurei.")
                return
        if re.fullmatch(r"(?:faz|faca|fazer)(?: um| o)? backup", c):
            try:
                caminho = backup.fazer_backup("pedido")
                self.dizer(f"Backup salvo em {caminho}.")
            except Exception as erro:
                diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                         {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                self.dizer(f"Não consegui fazer o backup: {erro}")
            return
        if re.fullmatch(r"(?:restaura|restaurar|recupera|recuperar)(?: o)?(?: ultimo)? backup", c):
            self.oferecer_restauro()
            return
        if self.banco_falho:
            self.dizer("O banco de dados está com falha. Diga: restaura o backup.")
            return
        if self.voz_pendente:
            id, self.voz_pendente = self.voz_pendente, None
            if re.fullmatch(r"(?:sim|pode|pode baixar|baixa|confirmo)", c):
                self.baixar_voz(id, ativar=True)
                return
        troca_voz = vozes.TROCA_VOZ.fullmatch(c)
        if troca_voz:
            id = vozes.pelo_nome(troca_voz.group(1))
            if id is None:
                self.dizer("Não conheço essa voz.")
            elif not next(v for v in vozes.listar() if v['id'] == id)['instalada']:
                self.voz_pendente = id
                self.mensagem("secretario", "Essa voz ainda não foi baixada, quer que eu baixe?")
                self.dizer("Essa voz ainda não foi baixada, quer que eu baixe?")
                self.conversa_ate = time.monotonic() + JANELA_CONVERSA
            else:
                vozes.usar(id)
                self.emitir_vozes()
                self.dizer("Voz alterada.")
            return
        troca = TROCA_MOTOR.search(c)
        if troca and len(c.split()) <= 6:  # frase curta: é comando, não tarefa
            nome = troca.group(1)
            nome = {"cloud": "claude", "groque": "grok", "chat gpt": "gpt",
                    "gemini cli": "gemini-cli", "jemini": "gemini"}.get(nome, nome)
            if nome == "gemini" and not provedores.ler_chave("gemini"):
                nome = "gemini-cli"
            self.trocar_motor(nome)
        elif c.startswith(("cancela", "para", "pare")):
            numero = re.search(r'\b(\d+)\b', c)
            self.cancelar(id=int(numero.group(1)) if numero else None, tudo='tudo' in c)
        elif re.fullmatch(r"(?:se )?reinici(?:a|ar|e)(?: (?:tudo|o app|o aplicativo|o motor))?", c.strip()):
            self.dizer("Reiniciando.", esperar=True)
            emitir(evento="reiniciar", completo=bool(re.search(r"\b(tudo|app|aplicativo)\b", c)))
            self.sair()
        elif c.startswith(("desligar", "desliga", "encerrar", "encerra")):
            self.dizer("Até logo.", esperar=True)
            self.sair()
        elif c.startswith("nova conversa"):
            self.sessao = None
            with self.trava:
                self.historicos_api.clear()
                self.sessoes_cli.clear()
                self.pendentes_api.clear()
            emitir(evento="nova_conversa")
            self.dizer("Ok, conversa nova.")
        else:
            self.conversa_ate = 0
            # Dividir pedidos pode chamar o Gemma (20–40 s na CPU): roda fora da thread que
            # escuta o microfone, senão ele ficaria surdo nesse tempo.
            threading.Thread(target=self.enfileirar, args=(comando,), daemon=True).start()

    def comando_celular(self, texto, aparelho):
        with self.trava:
            id = fila.adicionar(texto, motor=self.motor)
            try:
                with self.ponte.conectar() as con:
                    con.execute('INSERT INTO pedidos_celular (tarefa, aparelho) VALUES (?, ?)',
                                (id, aparelho))
            except Exception:
                fila.cancelar(id)
                raise
            self.emitir_fila()
        self.acordar.set()
        return [id]

    def notificar_ponte(self, **evento):
        self.config_mic['ponte_ativa'] = bool(evento.get('ativa'))
        emitir(**evento)

    def controlar_ponte(self, cmd):
        global _ponte
        try:
            if self.ponte is None:
                import ponte
                self.ponte = ponte.Ponte(self.comando_celular, self.notificar_ponte)
                _ponte = self.ponte
            if cmd['cmd'] == 'revogar_aparelho':
                if self.ponte.ativa:
                    async def revogar():
                        try:
                            await self.ponte.revogar(int(cmd['id']))
                            emitir(evento='ponte', ativa=True, qr=None, aparelhos=self.ponte.aparelhos())
                        except Exception as erro:
                            diagnostico.registrar_bug('ponte', erro)
                            emitir(evento='ponte', ativa=self.ponte.ativa,
                                   erro='Não foi possível revogar o aparelho.')
                    import asyncio
                    asyncio.run_coroutine_threadsafe(revogar(), self.ponte.loop)
            elif cmd.get('valor') is True:
                self.ponte.iniciar()
            else:
                self.ponte.desligar()
        except Exception as erro:
            diagnostico.registrar_bug('ponte', erro)
            emitir(evento='ponte', ativa=False, erro='Não foi possível controlar a ponte.')

    def enfileirar(self, comando):
        try:
            prioridade, texto = fila.detectar_prioridade(comando)
            pedidos = fila.dividir_pedidos(texto)
            with self.trava:
                ocupado = bool(self.trabalhos) or self.reparando
                if ARQ_MOTOR.exists():
                    salvo = ARQ_MOTOR.read_text(encoding='utf-8').strip()
                    if salvo in provedores.MOTORES:
                        self.motor = salvo
                for pedido in pedidos:
                    fila.adicionar(pedido, prioridade=prioridade, motor=self.motor)
                self.emitir_fila()
            self.dizer(f'Anotei {len(pedidos)} tarefas.' if len(pedidos) > 1 else
                       'Urgente, vou fazer agora.' if prioridade == 0 else
                       'Anotei, está na fila.' if ocupado else 'Certo.')
            self.acordar.set()
        except Exception as e:
            diagnostico.registrar_bug("motor", e, e.__traceback__,
                                     {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
            registrar('ERRO', f'Fila: {e}')
            emitir(evento='erro', texto=f'Não consegui anotar o pedido: {e}')

    def emitir_perfil(self):
        emitir(evento="perfil_atual", respostas=memoria.ler_perfil_inicial(),
               assuntos=list(memoria.ASSUNTOS), concluido=config.carregar().get("perfil_inicial") is True)

    def ouvir_comando(self):
        if self.ditado_pendente:
            self.ditado_pendente = False
            try:
                self.consultar_microfone()
                if self.mic.pausado or (self.apps_mic and self.config_mic.get("mic_em_chamada") == "liberar"):
                    emitir(evento="ditado", texto="", erro="Microfone liberado ou mudo; digite a resposta.")
                    return None
                self.ditando = True
                self.comando_mic_ate = 0.0
                self.atualizar_microfone()
                audio = self.mic.gravar_fala(espera_max=8) if self.mic.stream is not None else None
                emitir(evento="ditado", texto=transcrever(audio) if audio is not None else "")
            except Exception as erro:
                emitir(evento="ditado", texto="", erro=str(erro))
            finally:
                self.ditando = False
                self.comando_mic_ate = 0.0
                self.atualizar_microfone()
            return None
        self.atualizar_microfone()
        if self.mic.stream is None:
            time.sleep(0.1)
            return None
        audio = self.mic.gravar_fala(espera_max=0.5, detalhado=True)
        if audio is None or self.ditado_pendente:
            return None
        em_conversa = time.monotonic() < self.conversa_ate
        audio, pausas = audio
        detalhes = transcrever(audio, detalhado=True)
        texto = detalhes['texto']
        registro.evento("Transcrição", "ok" if texto else "")
        if not texto:
            return None
        achou = ATIVACAO.search(texto) or ativacao_tolerante(texto)
        if not achou and not em_conversa:
            return None  # não foi comigo: ignora
        comando = texto[achou.end():].strip() if achou else texto
        if not comando:
            if not self.apps_mic:
                bip()
            self.estado("escutando")
            audio = self.mic.gravar_fala(espera_max=8, detalhado=True)
            self.estado_ocioso()
            if audio is not None:
                audio, pausas = audio
                detalhes = transcrever(audio, detalhado=True)
                comando = detalhes['texto']
            else:
                comando = ""
        if comando:
            import padrao_fala
            try:
                termos = vocabulario.termos()
            except Exception:
                termos = []
            try:
                padrao_fala.registrar_fala(comando, detalhes['palavras'], pausas, termos=termos)
            except Exception as erro:
                registrar('ERRO', f'Padrão de fala: {erro}')
            emitir(evento='transcricao', texto=comando,
                   duvidosas=padrao_fala.duvidosas(detalhes['palavras'], termos))
            self.mensagem("voce", comando)
            self.comando_mic_ate = 0.0
            self.atualizar_microfone()
        return comando or None

    def consultar_microfone(self):
        with self.trava:
            agora = time.monotonic()
            if agora >= self.consultar_mic_apos:
                anteriores = self.apps_mic
                self.apps_mic = dispositivos.apps_usando_microfone()
                self.consultar_mic_apos = agora + 3
                if self.apps_mic and not anteriores:
                    interromper_fala()

    def atualizar_microfone(self):
        self.consultar_microfone()
        agora = time.monotonic()
        chamada = bool(self.apps_mic) and self.config_mic.get("mic_em_chamada") == "liberar"
        pedido = agora < self.comando_mic_ate
        demanda = self.config_mic.get("modo_microfone") == "sob_demanda"
        if agora >= self.conversa_ate and not pedido:
            self.demanda_ativa = False
        abrir = not self.mic.pausado and (pedido or (not chamada and (
            self.ditando or not demanda or (self.demanda_ativa and agora < self.conversa_ate))))
        if abrir:
            ok = self.mic.retomar()
            estado = "ouvindo" if ok else "indisponivel"
        else:
            self.mic.liberar()
            estado = "mudo" if self.mic.pausado else "liberado"
        app = ", ".join(self.apps_mic)
        aviso = "Microfone indisponível; tentando o dispositivo padrão a cada 2 s." if estado == "indisponivel" else ""
        atual = (estado, app, self.config_mic.get("modo_microfone"), aviso)
        if atual != self.ultimo_estado_mic:
            self.ultimo_estado_mic = atual
            emitir(evento="microfone", estado=estado, app=app, modo=atual[2], aviso=aviso)
            if aviso:
                emitir(evento="estado", estado="microfone_indisponivel", aviso=aviso)
            else:
                self.estado_ocioso()

    def vigiar_microfone(self):
        while self.ativo:
            self.consultar_microfone()
            # Fechar é imediato; abrir e calibrar ficam na thread de escuta.
            chamada = self.apps_mic and self.config_mic.get("mic_em_chamada") == "liberar"
            agora = time.monotonic()
            expirou = (self.config_mic.get("modo_microfone") == "sob_demanda"
                       and not self.ditando and agora >= max(self.comando_mic_ate, self.conversa_ate))
            if self.mic.pausado or expirou or (chamada and agora >= self.comando_mic_ate):
                self.mic.liberar()
            time.sleep(0.2)

    def ler_app(self):
        """Lê comandos do app Electron pelo stdin."""
        for linha in sys.stdin:
            try:
                cmd = json.loads(linha)
            except json.JSONDecodeError:
                continue
            tipo = cmd.get("cmd")
            if tipo == "perfil_atual":
                self.emitir_perfil()
                continue
            if tipo == "ditar":
                self.ditado_pendente = True
                continue
            if tipo == "perfil_inicial":
                try:
                    memoria.salvar_perfil_inicial(cmd.get("respostas"))
                    caminho = BASE / "config.json"
                    salvo = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
                    salvo["perfil_inicial"] = True
                    caminho.write_text(json.dumps(salvo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    emitir(evento="perfil_salvo")
                except Exception as erro:
                    emitir(evento="perfil_erro", texto=f"Não consegui salvar a apresentação: {erro}")
                continue
            if tipo == "bugs":
                self.emitir_bugs()
                continue
            if tipo in ("corrigir_bug", "ignorar_bug"):
                if tipo == "ignorar_bug":
                    registro.atualizar_bug(cmd['id'], estado='ignorado')
                    self.emitir_bugs()
                else:
                    self.pedir_reparo(cmd['id'], cmd.get('diretriz', ''))
                continue
            if tipo in ("vozes", "voz", "baixar_voz", "remover_voz", "amostra_voz"):
                try:
                    id = cmd.get("valor")
                    if tipo == "voz":
                        vozes.usar(id)
                    elif tipo == "baixar_voz":
                        self.baixar_voz(id)
                        continue
                    elif tipo == "remover_voz":
                        interromper_fala()
                        vozes.remover(id)
                    elif tipo == "amostra_voz":
                        self.amostra_voz(id)
                    self.emitir_vozes()
                except Exception as erro:
                    diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                             {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                    emitir(evento="erro", texto=str(erro))
                continue
            if tipo in ('ponte', 'revogar_aparelho'):
                self.controlar_ponte(cmd)
            elif tipo == "texto" and cmd.get("texto", "").strip():
                registrar("Você (texto)", cmd["texto"])
                self.executar(cmd["texto"].strip())
            elif tipo == "motor":
                self.trocar_motor(cmd.get("valor"))
            elif tipo == "chave":
                try:
                    provedores.salvar_chave(cmd.get("motor"), cmd.get("valor"))
                except Exception:
                    diagnostico.registrar_bug("motor", sys.exc_info()[1], sys.exc_info()[2])
                    emitir(evento="erro", texto="Não foi possível salvar a chave.")
                else:
                    self.emitir_motores()
            elif tipo == "cancelar":
                self.cancelar(id=cmd.get('id'))
            elif tipo == "mudo":
                self.mic.pausado = bool(cmd.get("valor"))
                self.estado_ocioso()
            elif tipo == "modo_microfone" and cmd.get("valor") in ("continuo", "sob_demanda"):
                self.config_mic["modo_microfone"] = cmd["valor"]
                try:
                    caminho = BASE / "config.json"
                    salvo = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
                    salvo["modo_microfone"] = cmd["valor"]
                    caminho.write_text(json.dumps(salvo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except Exception as erro:
                    diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                             {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                    emitir(evento="erro", texto=f"Não consegui salvar o modo do microfone: {erro}")
            elif tipo == "silencio":
                self.silencio = bool(cmd.get("valor"))
                if self.silencio:
                    interromper_fala()
            elif tipo == "sessao":
                self.sessao = cmd.get("id")
            elif tipo == "ouvir_agora":
                self.demanda_ativa = True
                self.comando_mic_ate = time.monotonic() + JANELA_CONVERSA
                self.conversa_ate = self.comando_mic_ate
                if not self.apps_mic:
                    bip()
            elif tipo == "sair":
                self.sair()
        self.sair()  # app fechou o stdin

    def emitir_nivel(self):
        while self.ativo:
            valor = 0 if self.mic.pausado else min(1, self.mic.nivel / self.mic.limiar / 4)
            emitir(evento="nivel", valor=round(valor, 3))
            time.sleep(0.15)

    def sair(self):
        self.ativo = False
        if self.ponte is not None:
            self.ponte.desligar()
        interromper_fala()
        with self.trava:
            for trabalho in self.trabalhos.values():
                trabalho['cancelado'] = True
                proc = trabalho['proc']
                if proc and proc.poll() is None:
                    subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        emitir(evento="saindo")
        self.mic.fechar()
        os._exit(0)  # pode ser chamado da thread que lê o app

    def oferecer_restauro(self, motivo=""):
        try:
            ultimo = backup.ultimo_backup_integro()
        except Exception as erro:
            diagnostico.registrar_bug("backup", erro, erro.__traceback__)
            ultimo = None
        if not ultimo:
            self.dizer(f"{motivo} Não encontrei um backup íntegro para restaurar.".strip())
            return
        self.restauro_pendente = ultimo['nome']
        quando = datetime.fromisoformat(ultimo['criado']).strftime("%d/%m às %H:%M")
        texto = (f"{motivo} Posso restaurar o backup de {quando}? "
                 "Os dados atuais ficam guardados antes.").strip()
        self.mensagem("secretario", texto)
        self.dizer(texto)

    def restaurar(self, nome):
        with self.trava:
            ocupado = bool(self.trabalhos) or self.reparando
        if ocupado:
            self.dizer("Tem tarefa em andamento. Cancele ou espere terminar antes de restaurar.")
            return
        try:
            # O próprio motor segura a trava motor_ativo; por isso restaura por dentro.
            resultado = backup.restaurar(nome, confirmado=True, pelo_motor=True)
        except Exception as erro:
            diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                     {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
            self.dizer(f"Não consegui restaurar: {erro}")
            return
        registrar("Sistema", f"backup {nome} restaurado; cópia de segurança: {resultado['seguranca']}")
        self.dizer("Backup restaurado. Vou me reiniciar.", esperar=True)
        emitir(evento="reiniciar", completo=False)
        self.sair()

    def emitir_bugs(self):
        emitir(evento='bugs', lista=registro.listar_bugs())

    def pedir_reparo(self, id, diretriz=''):
        bug = registro.detalhe_bug(id)
        if bug is None:
            return
        self.reparo_pendente = (int(id), diretriz[:1000])
        texto = f"Posso corrigir o problema {id}: {bug['resumo']}?"
        self.mensagem('secretario', texto)
        self.dizer(texto)

    def iniciar_reparo(self, id, diretriz):
        with self.trava:
            if self.ocupado or self.reparando:
                self.dizer('Aguarde as tarefas terminarem e peça o reparo novamente.')
                return
            self.reparando = True

        def trabalhar_reparo():
            try:
                resultado = reparo.executar(id, diretriz, aprovado=True)
                if resultado['ok']:
                    emitir(evento='reparo', commit=resultado['commit'], id=id)
                    self.reinicio_reparo = True
                self.mensagem('secretario', resultado['texto'])
                self.dizer(resultado['texto'])
                self.emitir_bugs()
            finally:
                self.reparando = False
                self.acordar.set()

        threading.Thread(target=trabalhar_reparo, daemon=True).start()

    def testar_microfone(self):
        if self.apps_mic:
            return 'adiado durante chamada'
        if self.mic.stream is not None:
            return True
        import sounddevice
        with sounddevice.InputStream(channels=1, device=self.config_mic.get('microfone')):
            return True

    def vigiar_saude(self):
        ultima = registro.ultimo_evento('Saude completa')
        ultimo_dia = ultima['ts'][:10] if ultima else ''
        diagnostico.importar_quedas()
        diagnostico.verificar_saude(microfone=self.testar_microfone)
        while self.ativo:
            try:
                if not self.ocupado and not self.reparando and not self.apps_mic and not self.falando:
                    hoje = datetime.now().date().isoformat()
                    import segundo_plano
                    if ultimo_dia != hoje and segundo_plano.ocioso_ha() >= 60:
                        with self.trava:
                            pode = not self.ocupado and not self.reparando
                            if pode:
                                self.reparando = True
                        if pode:
                            try:
                                diagnostico.verificar_saude(completo=True,
                                    microfone=self.testar_microfone)
                                registro.evento('Saude completa', hoje)
                                ultimo_dia = hoje
                            finally:
                                self.reparando = False
                                self.acordar.set()
                    diagnostico.detectar_sintomas()
                    for arquivo in (BASE / 'sinais').glob('corrigir_*.json'):
                        dados = json.loads(arquivo.read_text(encoding='utf-8'))
                        self.pedir_reparo(dados['id'], dados.get('diretriz', ''))
                        arquivo.unlink()
                    for bug in registro.listar_bugs():
                        if (bug['estado'] in ('novo', 'informado', 'falhou')
                                and bug['avisado_em'] != hoje and not self.reparo_pendente
                                and not self.restauro_pendente and not self.voz_pendente
                                and not self.reinicio_reparo):
                            texto = (f"Encontrei um problema: {bug['resumo']}. Quer que eu tente corrigir? "
                                     'Se tiver alguma orientação, pode falar.')
                            self.reparo_pendente = (bug['id'], '')
                            self.mensagem('secretario', texto)
                            self.dizer(texto)
                            registro.atualizar_bug(bug['id'], estado='informado', avisado_em=hoje)
                            break
                    self.emitir_bugs()
            except Exception as erro:
                diagnostico.registrar_bug('vigia_saude', erro, erro.__traceback__)
            time.sleep(30)

    def rodar(self):
        global JANELA_CONVERSA
        self.preparar_memoria()
        JANELA_CONVERSA = float(self.config_mic.get("janela_conversa", 15))
        self.consultar_microfone()
        threading.Thread(target=self.vigiar_microfone, daemon=True).start()
        registro.preparar_banco()
        integridade = backup.verificar_banco()
        threading.Thread(target=self.falar_fila, daemon=True).start()
        if integridade != "ok":
            # Modo recuperação: o motor continua vivo (sair faria o app reiniciá-lo em
            # loop) e só aceita restaurar; a fila não roda porque depende do banco.
            self.banco_falho = True
            emitir(evento="erro", texto=f"Integridade do banco: {integridade}")
            self.oferecer_restauro("O banco de dados apresentou falha.")
        else:
            try:
                backup.backup_diario()
            except Exception as erro:
                diagnostico.registrar_bug("motor", erro, erro.__traceback__,
                                         {"motor": getattr(self, "motor", ""),
                                          "pedido": getattr(_contexto, "trabalho", {}).get("comando", "")})
                emitir(evento="erro", texto=f"Não consegui fazer o backup diário: {erro}")
            diagnostico.instalar_hooks()
            threading.Thread(target=self.vigiar_saude, daemon=True).start()
            fila.recuperar()
            self.emitir_fila()
            threading.Thread(target=self.despachar, daemon=True).start()
        self.emitir_motores()
        aquecer_voz()
        if IPC:
            self.emitir_vozes()
            self.emitir_perfil()
            threading.Thread(target=self.ler_app, daemon=True).start()
            threading.Thread(target=self.emitir_nivel, daemon=True).start()
        registrar("Sistema", f"ouvindo (limiar de voz {self.mic.limiar:.3f}). Diga 'secretário' + comando.")
        self.estado_ocioso()
        if not IPC:
            self.dizer("Secretário pronto.")
        while self.ativo:
            comando = self.ouvir_comando()
            if comando:
                self.executar(comando)


if __name__ == "__main__":
    diagnostico.instalar_hooks()
    if not IPC:
        print("Carregando reconhecimento de voz...", flush=True)
    emitir(evento="estado", estado="carregando")
    import numpy as np
    transcrever(np.zeros(16000, dtype="float32"))  # carrega o modelo antes de começar
    with backup.motor_ativo():
        Assistente().rodar()
