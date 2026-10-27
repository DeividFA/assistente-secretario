"""Adaptadores dos agentes de linha de comando.

Help local: codex-cli 0.164.0 (exec e exec resume), Qwen 0.21.5.
Gemini não instalado: comando e campo response seguem a documentação conhecida;
o formato não foi conferido localmente. Os helps não descrevem os eventos JSON.
"""

import re
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


EXECUTAVEIS = {"claude": "claude", "codex": "codex", "gemini-cli": "gemini", "qwen": "qwen"}


def montar_comando(nome, pedido, sessao=None, prompt_sistema="", pasta=None):
    if nome not in EXECUTAVEIS:
        raise ValueError("Motor de linha de comando desconhecido.")
    prompt = f"{prompt_sistema}\n\nPedido: {pedido}"
    if nome == "codex":
        # As opções de exec não aceitas por resume ficam antes do subcomando.
        # --skip-git-repo-check: a pasta do usuário não é um repositório git.
        comando = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write",
                   "-C", str(Path(pasta) if pasta is not None else Path.home())]
        if sessao:
            comando.extend(["resume", sessao])
        return comando + ["--json", "--", prompt]
    comando = [EXECUTAVEIS[nome], "-p", prompt, "--output-format", "json"]
    if nome == "claude":
        comando.extend(["--permission-mode", "auto"])
    if sessao:
        comando.extend(["--resume", sessao])
    return comando


def interpretar_linha(nome, linha):
    if nome not in EXECUTAVEIS:
        raise ValueError("Motor de linha de comando desconhecido.")
    try:
        dados = json.loads(linha)
    except (ValueError, TypeError):
        return None
    if not isinstance(dados, dict):
        return None
    if nome == "codex":
        tipo = dados.get("type")
        if tipo == "thread.started" and isinstance(dados.get("thread_id"), str):
            return {"tipo": "sessao", "sessao": dados["thread_id"]}
        item = dados.get("item")
        if not isinstance(item, dict):
            return None
        if tipo == "item.completed" and item.get("type") == "agent_message":
            if isinstance(item.get("text"), str):
                return {"tipo": "resposta", "texto": item["text"]}
        if tipo == "item.started" and item.get("type") in (
                "command_execution", "mcp_tool_call", "web_search", "file_change"):
            return {"tipo": "ferramenta", "nome": item.get("tool") or item["type"],
                    "id": item.get("id"), "comando": item.get("command", "")}
        return None
    # Claude usa result; Gemini usa response; Qwen também pode usar result.
    texto = dados.get("result") if nome == "claude" else dados.get("response", dados.get("result"))
    if isinstance(texto, str) and not dados.get("is_error") and not dados.get("error"):
        evento = {"tipo": "resposta", "texto": texto}
        if isinstance(dados.get("session_id"), str):
            evento["sessao"] = dados["session_id"]
        return evento
    if dados.get("type") in ("init", "system") and isinstance(dados.get("session_id"), str):
        return {"tipo": "sessao", "sessao": dados["session_id"]}
    return None


def _matar_arvore(proc):
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        else:
            proc.kill()
    proc.wait()


def resolver_executavel(nome):
    """Lista de argumentos para iniciar o CLI sem passar pelo cmd.exe.

    Os atalhos do npm no Windows (codex.cmd, qwen.cmd, gemini.cmd) só chamam
    `node <arquivo.js>`; executá-los pelo cmd.exe quebraria o pedido em quebras de linha e
    interpretaria &, | e aspas do texto ditado. Por isso lemos o .js do atalho."""
    caminho = shutil.which(nome)
    if not caminho:
        return [nome]
    if caminho.lower().endswith((".cmd", ".bat")):
        texto = Path(caminho).read_text(encoding="utf-8", errors="replace")
        js = re.findall(r'"%dp0%\\([^"]+\.js)"', texto)
        node = shutil.which("node")
        if js and node:
            return [node, str(Path(caminho).parent / js[-1])]
    return [caminho]


def executar(nome, pedido, ao_evento, sessao=None, prompt_sistema="", pasta=None, env=None):
    """Emite eventos e retorna o resultado após o término.

    O primeiro callback recebe {tipo: "processo", proc: Popen}. O chamador pode
    guardar o PID e cancelar com taskkill /pid PID /T /F enquanto a leitura segue.
    Falhas do CLI levantam RuntimeError; o processo é encerrado se o callback falhar.
    """
    comando = montar_comando(nome, pedido, sessao, prompt_sistema, pasta)
    comando = resolver_executavel(comando[0]) + comando[1:]
    resultado = {"resposta": "", "sessao": sessao, "ferramentas": [], "proc": None}

    def emitir(evento):
        if evento is None:
            return
        if evento.get("sessao"):
            resultado["sessao"] = evento["sessao"]
        if evento["tipo"] == "resposta":
            resultado["resposta"] = evento["texto"]
        elif evento["tipo"] == "ferramenta":
            resultado["ferramentas"].append(evento["nome"])
        ao_evento(evento)

    # stderr em arquivo evita bloquear o filho quando o buffer do pipe enche.
    with tempfile.TemporaryFile() as erros:
        proc = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=erros,
            text=True, encoding="utf-8", errors="replace",
            cwd=str(Path(pasta) if pasta is not None else Path.home()), env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        resultado["proc"] = proc
        try:
            ao_evento({"tipo": "processo", "proc": proc})
            partes = []
            for linha in proc.stdout:
                if nome == "codex":
                    emitir(interpretar_linha(nome, linha))
                else:
                    partes.append(linha)
            codigo = proc.wait()
            if codigo:
                raise RuntimeError(f"O motor {nome} terminou com código {codigo}.")
            if nome != "codex":
                # --output-format json pode produzir JSON indentado ou uma lista.
                try:
                    dados = json.loads("".join(partes))
                except ValueError:
                    raise RuntimeError(f"Resposta JSON inválida do motor {nome}.") from None
                for item in dados if isinstance(dados, list) else [dados]:
                    emitir(interpretar_linha(nome, json.dumps(item)))
            if not resultado["resposta"]:
                raise RuntimeError(f"O motor {nome} não devolveu uma resposta.")
            return resultado
        finally:
            try:
                _matar_arvore(proc)
            finally:
                proc.stdout.close()
