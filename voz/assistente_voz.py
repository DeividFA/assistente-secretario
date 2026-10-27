"""Motor do secretário: ouve o microfone, entende comandos e executa via Claude Code.

Só age quando ouve a palavra de ativação "secretário" (ou durante alguns segundos
depois de uma resposta, para ele responder perguntas como "Posso enviar?").

Modos:
  python assistente_voz.py          terminal (texto no console)
  python assistente_voz.py --ipc    controlado pelo app Electron: emite eventos JSON
                                    no stdout e recebe comandos JSON no stdin

Comandos falados de controle (depois de "secretário"):
  "cancela" / "para"   interrompe a tarefa   ·  "nova conversa"  começa outra sessão
  "desligar"           encerra o motor

Comandos do app (stdin, uma linha JSON cada):
  {"cmd":"texto","texto":"..."}  {"cmd":"cancelar"}  {"cmd":"mudo","valor":true}
  {"cmd":"silencio","valor":true}  {"cmd":"sessao","id":"..."|null}
  {"cmd":"ouvir_agora"}  {"cmd":"sair"}
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from comum import BASE, Microfone, bip, falar, normalizar, texto_para_fala, transcrever

IPC = "--ipc" in sys.argv
ATIVACAO = re.compile(r"\bsecret[aá]ri[oa]\b[\s,.!?:;-]*", re.I)
JANELA_CONVERSA = 15  # segundos após uma resposta em que dá para responder sem dizer "secretário"
LOG = BASE / "log_voz.txt"
PROMPT_VOZ = (BASE / "voz_prompt.md").read_text(encoding="utf-8")
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")

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
}

if IPC:
    sys.stdout.reconfigure(encoding="utf-8")
_saida = threading.Lock()


def emitir(**evento):
    if IPC:
        with _saida:
            sys.stdout.write(json.dumps(evento, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def registrar(quem, texto):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {quem}: {texto}"
    if not IPC:
        print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def nome_ferramenta(nome):
    for prefixo, rotulo in NOMES_FERRAMENTAS.items():
        if nome.startswith(prefixo):
            return rotulo
    return nome


class Assistente:
    def __init__(self):
        self.mic = Microfone()
        self.sessao = None
        self.proc = None
        self.ocupado = False
        self.cancelado = False
        self.silencio = False  # não falar as respostas (equivalente ao "ensurdecer" do Discord)
        self.conversa_ate = 0.0
        self.ativo = True

    def estado(self, estado):
        emitir(evento="estado", estado=estado)

    def estado_ocioso(self):
        self.estado("pensando" if self.ocupado else ("mudo" if self.mic.pausado else "ouvindo"))

    def mensagem(self, autor, texto):
        registrar({"voce": "Você", "secretario": "Secretário"}.get(autor, autor), texto)
        emitir(evento="mensagem", autor=autor, texto=texto)

    def dizer(self, texto):
        """Fala com o microfone mudo, para não ouvir a própria voz."""
        if self.silencio:
            return
        self.estado("falando")
        self.mic.mudo = True
        try:
            falar(texto_para_fala(texto))
        finally:
            time.sleep(0.2)
            self.mic.limpar()
            self.mic.mudo = False
            self.estado_ocioso()

    def tarefa(self, comando):
        self.ocupado = True
        self.cancelado = False
        self.estado("pensando")
        try:
            args = [CLAUDE, "-p", comando, "--output-format", "stream-json", "--verbose",
                    "--permission-mode", "auto", "--append-system-prompt", PROMPT_VOZ]
            if self.sessao:
                args += ["--resume", self.sessao]
            # stdin=DEVNULL: senão o claude -p fica esperando ler o canal de comandos do app.
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, cwd=str(Path.home()), text=True,
                                         encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
            resposta = None
            erro = ""
            for linha in self.proc.stdout:
                try:
                    ev = json.loads(linha)
                except json.JSONDecodeError:
                    erro = (erro + linha)[-2000:]
                    continue
                if ev.get("session_id") and ev["session_id"] != self.sessao:
                    self.sessao = ev["session_id"]
                    emitir(evento="sessao", id=self.sessao)
                if ev.get("type") == "assistant":
                    for bloco in ev.get("message", {}).get("content", []):
                        if bloco.get("type") == "tool_use":
                            emitir(evento="ferramenta", nome=nome_ferramenta(bloco.get("name", "")))
                elif ev.get("type") == "result":
                    resposta = ev.get("result")
            self.proc.wait()
            if self.cancelado:
                return
            if resposta is None:
                registrar("ERRO", erro.strip()[-500:])
                emitir(evento="erro", texto=erro.strip()[-500:] or "O Claude não respondeu.")
                self.dizer("Deu um erro ao executar. Os detalhes estão na tela.")
                return
            resposta = resposta or "Pronto."
            self.mensagem("secretario", resposta)
            self.dizer(resposta)
            self.conversa_ate = time.monotonic() + JANELA_CONVERSA
        finally:
            self.proc = None
            self.ocupado = False
            self.estado_ocioso()

    def cancelar(self):
        if self.proc and self.proc.poll() is None:
            self.cancelado = True
            self.proc.kill()
            self.mensagem("sistema", "Tarefa cancelada.")
            self.dizer("Tarefa cancelada.")
        else:
            self.dizer("Não tem nada rodando.")

    def executar(self, comando):
        """Trata comandos de controle ou dispara uma tarefa."""
        c = normalizar(comando)
        if c.startswith(("cancela", "para", "pare")):
            self.cancelar()
        elif c.startswith(("desligar", "desliga", "encerrar", "encerra")):
            self.dizer("Até logo.")
            self.sair()
        elif c.startswith("nova conversa"):
            self.sessao = None
            emitir(evento="nova_conversa")
            self.dizer("Ok, conversa nova.")
        elif self.ocupado:
            self.dizer("Ainda estou na tarefa anterior. Diga secretário, cancela, se quiser parar.")
        else:
            self.conversa_ate = 0
            threading.Thread(target=self.tarefa, args=(comando,), daemon=True).start()

    def ouvir_comando(self):
        audio = self.mic.gravar_fala()
        em_conversa = time.monotonic() < self.conversa_ate
        texto = transcrever(audio)
        if not texto:
            return None
        achou = ATIVACAO.search(texto)
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
            elif tipo == "cancelar":
                self.cancelar()
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
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        emitir(evento="saindo")
        self.mic.fechar()
        os._exit(0)  # pode ser chamado da thread que lê o app

    def rodar(self):
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
