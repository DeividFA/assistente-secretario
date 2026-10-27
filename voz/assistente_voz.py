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
import agente_local
import motores_cli
import provedores
from vocabulario import ativacao_tolerante

from comum import BASE, Microfone, bip, falar, normalizar, texto_para_fala, transcrever

IPC = "--ipc" in sys.argv
ATIVACAO = re.compile(r"\bsecret[aá]ri[oa]\b[\s,.!?:;-]*", re.I)
JANELA_CONVERSA = 15  # segundos após uma resposta em que dá para responder sem dizer "secretário"
LOG = BASE / "log_voz.txt"
PROMPT_VOZ = (BASE / "voz_prompt.md").read_text(encoding="utf-8")
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


def emitir(**evento):
    if evento.get('evento') in ('mensagem', 'ferramenta', 'erro'):
        evento.setdefault('tarefa', getattr(_contexto, 'id', None))
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
        print(f"registro SQLite falhou: {e}", file=sys.stderr)


def nome_ferramenta(nome):
    for prefixo, rotulo in NOMES_FERRAMENTAS.items():
        if nome.startswith(prefixo):
            return rotulo
    return nome


class Assistente:
    def __init__(self):
        self.mic = Microfone()
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

    @property
    def ocupado(self):
        with self.trava:
            return bool(self.trabalhos)

    def emitir_fila(self):
        emitir(evento="fila", tarefas=fila.listar())

    def despachar(self):
        while self.ativo:
            self.acordar.clear()
            try:
                with self.trava:
                    pendentes = [t for t in fila.listar() if t['status'] == 'pendente']
                    if pendentes:
                        motor = pendentes[0]['motor']
                        locais = any(t['motor'] == 'gemma' for t in self.trabalhos.values())
                        vaga = (not self.trabalhos if motor == 'gemma'
                                else not locais and len(self.trabalhos) < 2)
                        if vaga:
                            tarefa = fila.proxima()
                            if tarefa:
                                tarefa.update(proc=None, cancelado=False,
                                              derivada=bool(self.trabalhos), sessao=self.sessao)
                                if self.trabalhos:
                                    tarefa['simultanea'] = True
                                    for outra in self.trabalhos.values():
                                        outra['simultanea'] = True
                                self.trabalhos[tarefa['id']] = tarefa
                                self.emitir_fila()
                                threading.Thread(target=self.trabalhar, args=(tarefa,), daemon=True).start()
                                continue
            except Exception as e:
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
                if tarefa is None or not tarefa['cancelado']:
                    self._dizer(texto)
                    if tarefa is not None:
                        self.conversa_ate = time.monotonic() + JANELA_CONVERSA
            except Exception as e:
                registrar('ERRO', f'Fala: {e}')
            finally:
                pronto.set()
                self.falas.task_done()

    def dizer(self, texto, esperar=False):
        trabalho = getattr(_contexto, 'trabalho', None)
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
                    else 'mudo' if self.mic.pausado else 'ouvindo')

    def mensagem(self, autor, texto):
        registrar({"voce": "Você", "secretario": "Secretário"}.get(autor, autor), texto)
        emitir(evento="mensagem", autor=autor, texto=texto)

    def _dizer(self, texto):
        """Fala com o microfone mudo, para não ouvir a própria voz."""
        if self.silencio:
            return
        self.falando = True
        self.estado("falando")
        self.mic.mudo = True
        try:
            falar(texto_para_fala(texto))
        finally:
            time.sleep(0.2)
            self.mic.limpar()
            self.mic.mudo = False
            self.falando = False
            self.estado_ocioso()

    def emitir_motores(self):
        emitir(evento="motores", lista=provedores.listar(), atual=self.motor)

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
            import memoria
            ctx = memoria.contexto(comando)
        except Exception as e:
            registrar("ERRO", f"Contexto de memória: {e}")
        if motor != "claude":
            self.tarefa_provedor(comando, motor, ctx)
            return
        if ctx:
            comando = ctx + "\n\nPedido: " + comando
        tarefa_id = inicio_tarefa(comando, "claude")
        status = "erro"
        ferramentas = []
        resposta = None
        erro = ""
        try:
            args = motores_cli.resolver_executavel(CLAUDE) + ["-p", comando, "--output-format", "stream-json", "--verbose",
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
                            if nome and nome not in ferramentas:
                                ferramentas.append(nome)
                            emitir(evento="ferramenta", nome=nome_ferramenta(bloco.get("name", "")))
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
            self.conversa_ate = time.monotonic() + JANELA_CONVERSA
        except Exception as e:
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

    def enfileirar(self, comando):
        try:
            prioridade, texto = fila.detectar_prioridade(comando)
            pedidos = fila.dividir_pedidos(texto)
            with self.trava:
                ocupado = bool(self.trabalhos)
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
            registrar('ERRO', f'Fila: {e}')
            emitir(evento='erro', texto=f'Não consegui anotar o pedido: {e}')

    def ouvir_comando(self):
        audio = self.mic.gravar_fala()
        em_conversa = time.monotonic() < self.conversa_ate
        texto = transcrever(audio)
        if not texto:
            return None
        achou = ATIVACAO.search(texto) or ativacao_tolerante(texto)
        if not achou and not em_conversa:
            return None  # não foi comigo: ignora
        comando = texto[achou.end():].strip() if achou else texto
        if not comando:
            bip()
            self.estado("escutando")
            audio = self.mic.gravar_fala(espera_max=8)
            self.estado_ocioso()
            comando = transcrever(audio) if audio is not None else ""
        if comando:
            self.mensagem("voce", comando)
        return comando or None

    def ler_app(self):
        """Lê comandos do app Electron pelo stdin."""
        for linha in sys.stdin:
            try:
                cmd = json.loads(linha)
            except json.JSONDecodeError:
                continue
            tipo = cmd.get("cmd")
            if tipo == "texto" and cmd.get("texto", "").strip():
                registrar("Você (texto)", cmd["texto"])
                self.executar(cmd["texto"].strip())
            elif tipo == "motor":
                self.trocar_motor(cmd.get("valor"))
            elif tipo == "chave":
                try:
                    provedores.salvar_chave(cmd.get("motor"), cmd.get("valor"))
                except Exception:
                    emitir(evento="erro", texto="Não foi possível salvar a chave.")
                else:
                    self.emitir_motores()
            elif tipo == "cancelar":
                self.cancelar(id=cmd.get('id'))
            elif tipo == "mudo":
                self.mic.pausado = bool(cmd.get("valor"))
                self.mic.limpar()
                self.estado_ocioso()
            elif tipo == "silencio":
                self.silencio = bool(cmd.get("valor"))
            elif tipo == "sessao":
                self.sessao = cmd.get("id")
            elif tipo == "ouvir_agora":
                bip()
                self.conversa_ate = time.monotonic() + 10
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

    def rodar(self):
        self.emitir_motores()
        fila.recuperar()
        self.emitir_fila()
        threading.Thread(target=self.falar_fila, daemon=True).start()
        threading.Thread(target=self.despachar, daemon=True).start()
        if IPC:
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
    if not IPC:
        print("Carregando reconhecimento de voz...", flush=True)
    emitir(evento="estado", estado="carregando")
    import numpy as np
    transcrever(np.zeros(16000, dtype="float32"))  # carrega o modelo antes de começar
    Assistente().rodar()
