"""Registro de motores e acesso às credenciais e APIs de conversa."""

import copy
import json as json_modulo
import os
import shutil
import urllib.error
import urllib.request

import keyring

import config


MOTORES = {
    "claude": {"rotulo": "Claude Code", "tipo": "cli", "executavel": "claude"},
    "codex": {"rotulo": "Codex", "tipo": "cli", "executavel": "codex"},
    "gemini-cli": {"rotulo": "Gemini CLI", "tipo": "cli", "executavel": "gemini"},
    "qwen": {"rotulo": "Qwen", "tipo": "cli", "executavel": "qwen"},
    "grok": {"rotulo": "Grok", "tipo": "api", "url": "https://api.x.ai/v1",
             "modelo": "grok-4", "chave": "grok"},
    "gpt": {"rotulo": "GPT", "tipo": "api", "url": "https://api.openai.com/v1",
            "modelo": "gpt-5", "chave": "gpt"},
    "gemini": {"rotulo": "Gemini", "tipo": "api",
               "url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "modelo": "gemini-2.5-flash", "chave": "gemini"},
    "deepseek": {"rotulo": "DeepSeek", "tipo": "api", "url": "https://api.deepseek.com/v1",
                 "modelo": "deepseek-chat", "chave": "deepseek"},
    "mistral": {"rotulo": "Mistral", "tipo": "api", "url": "https://api.mistral.ai/v1",
                "modelo": "mistral-large-latest", "chave": "mistral"},
    "openrouter": {"rotulo": "OpenRouter", "tipo": "api", "url": "https://openrouter.ai/api/v1",
                   "modelo": "", "chave": "openrouter"},
    "gemma": {"rotulo": "Gemma (local)", "tipo": "api", "url": "http://localhost:11434/v1",
              "modelo": "gemma3:4b", "chave": None},
}

VARIAVEIS_CHAVES = {
    "grok": "XAI_API_KEY", "gpt": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY", "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def salvar_chave(nome, valor):
    if nome not in VARIAVEIS_CHAVES:
        raise ValueError("Credencial desconhecida.")
    try:
        keyring.set_password("secretario", nome, valor)
    except Exception:
        raise RuntimeError("Não foi possível salvar a chave no keyring.") from None


def ler_chave(nome):
    if nome not in VARIAVEIS_CHAVES:
        return None
    try:
        valor = keyring.get_password("secretario", nome)
    except Exception:
        valor = None
    return valor or os.environ.get(VARIAVEIS_CHAVES[nome]) or None


def disponivel(nome):
    motor = MOTORES.get(nome)
    if motor is None:
        return False, "Motor desconhecido."
    if motor["tipo"] == "cli":
        if shutil.which(motor["executavel"]):
            return True, ""
        return False, "Executável não encontrado."
    if motor["chave"] is not None:
        return (True, "") if ler_chave(motor["chave"]) else (False, "Chave não configurada.")
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resposta:
            json_modulo.loads(resposta.read().decode("utf-8"))
        return True, ""
    except Exception:
        return False, "Ollama indisponível."


def listar():
    lista = []
    for nome, motor in MOTORES.items():
        ativo, motivo = disponivel(nome)
        lista.append({"nome": nome, "rotulo": motor["rotulo"], "tipo": motor["tipo"],
                      "disponivel": ativo, "motivo": motivo})
    return lista


def chamar_api(nome, mensagens, json=False, imagens=None, timeout=120):
    motor = MOTORES.get(nome)
    if motor is None or motor["tipo"] != "api":
        raise ValueError("Motor de API desconhecido.")
    chave = ler_chave(motor["chave"]) if motor["chave"] else None
    if motor["chave"] and not chave:
        raise RuntimeError("Chave não configurada.")
    try:
        modelos = config.carregar().get("modelos", {})
        modelo = modelos.get(nome, motor["modelo"])
        if not isinstance(modelo, str) or not modelo.strip():
            raise ValueError()
    except Exception:
        raise RuntimeError("Configure um modelo válido para o motor.") from None
    try:
        copia = copy.deepcopy(mensagens)
        if imagens:
            ultima = next(m for m in reversed(copia) if m.get("role") == "user")
            conteudo = ultima.get("content", "")
            partes = [{"type": "text", "text": conteudo}] if isinstance(conteudo, str) else list(conteudo)
            partes.extend({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + imagem}} for imagem in imagens)
            ultima["content"] = partes
        dados = {"model": modelo, "messages": copia, "temperature": 0.2}
        if json:
            dados["response_format"] = {"type": "json_object"}
        cabecalhos = {"Content-Type": "application/json"}
        if chave:
            cabecalhos["Authorization"] = "Bearer " + chave
        pedido = urllib.request.Request(
            motor["url"].rstrip("/") + "/chat/completions",
            data=json_modulo.dumps(dados).encode("utf-8"), headers=cabecalhos, method="POST")
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            resultado = json_modulo.loads(resposta.read().decode("utf-8"))
        texto = resultado["choices"][0]["message"]["content"]
        if not isinstance(texto, str):
            raise ValueError()
        return texto
    except urllib.error.HTTPError as erro:
        # Não reproduzir corpo, cabeçalhos ou motivo enviados pelo servidor.
        status = erro.code if isinstance(erro.code, int) else "desconhecido"
        raise RuntimeError(f"Erro HTTP {status}: chamada à API recusada.") from None
    except Exception:
        raise RuntimeError("Falha ao chamar a API ou interpretar a resposta.") from None
