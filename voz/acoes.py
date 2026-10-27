"""Catálogo de ações do motor local, sem iniciar dispositivos ao importar."""

import importlib
import inspect
import re
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

from comum import normalizar
from segundo_plano import OCUPADO


def _sentidos(nome, *args, **kwargs):
    return getattr(importlib.import_module("sentidos_mcp"), nome)(*args, **kwargs)


def abrir(alvo: str):
    return _sentidos("abrir", alvo)


def abrir_pasta(nome: str):
    pastas = {"documentos": "Documents", "downloads": "Downloads",
              "area de trabalho": "Desktop", "imagens": "Pictures",
              "musicas": "Music", "videos": "Videos"}
    pasta = pastas.get(normalizar(nome))
    return abrir(str(Path.home() / pasta) if pasta else nome)


def pesquisar_web(consulta: str):
    return abrir("https://www.google.com/search?q=" + quote_plus(consulta))


def ver_tela():
    return _sentidos("salvar_tela")


def foto_camera():
    return _sentidos("salvar_foto")


def clicar(x: int, y: int):
    return _sentidos("clicar", x, y)


def digitar(texto: str, enter: bool = False):
    return _sentidos("digitar", texto, enter=enter)


def teclas(combinacao: str):
    return _sentidos("teclas", combinacao)


def rolar(quantidade: int):
    return _sentidos("rolar", quantidade)


def janelas():
    return _sentidos("janelas")


def focar_janela(titulo: str):
    return _sentidos("focar_janela", titulo)


def comando_seguro(cmd) -> bool:
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    # Também bloqueia expressões e expansão de variáveis dentro dos argumentos.
    if re.search(r"[;&>`$(){}\r\n\x00]|(?:Invoke|Remove|Set|Stop|Start)-", cmd, re.I):
        return False
    # Por precaução, recusa também barras em argumentos entre aspas.
    trechos = re.split(r"\|", cmd)
    leitura = {"get-childitem", "get-date", "get-process", "get-computerinfo",
               "get-volume", "get-netipaddress", "get-clipboard", "test-path", "get-content"}
    filtros = {"select-object", "where-object", "sort-object", "measure-object",
               "format-table", "format-list"}
    for indice, trecho in enumerate(trechos):
        if trecho.count('"') % 2 or trecho.count("'") % 2:
            return False
        partes = trecho.strip().split(maxsplit=1)
        if not partes or partes[0].lower() not in (leitura if indice == 0 else filtros):
            return False
    return True


def comando(powershell: str):
    resultado = subprocess.run(
        ["powershell", "-NoProfile", "-Command", powershell],
        capture_output=True, text=True, timeout=20,
    )
    texto = (resultado.stdout + resultado.stderr)[:1500]
    if resultado.returncode:
        raise RuntimeError(texto or f"PowerShell terminou com código {resultado.returncode}.")
    return texto


def lembrete(quando: str, texto: str):
    return _sentidos("lembrete", quando, texto)


ACOES = {
    "abrir": {"funcao": abrir, "descricao": "Abrir programa, arquivo ou URL", "args": {"alvo": "programa, caminho ou URL"}, "confirmar": False},
    "abrir_pasta": {"funcao": abrir_pasta, "descricao": "Abrir pasta", "args": {"nome": "pasta conhecida ou caminho"}, "confirmar": False},
    "pesquisar_web": {"funcao": pesquisar_web, "descricao": "Pesquisar no Google", "args": {"consulta": "texto da pesquisa"}, "confirmar": False},
    "ver_tela": {"funcao": ver_tela, "descricao": "Ver a tela", "args": {}, "confirmar": False},
    "foto_camera": {"funcao": foto_camera, "descricao": "Fotografar com autorização explícita", "args": {}, "confirmar": False},
    "clicar": {"funcao": clicar, "descricao": "Clicar na tela", "args": {"x": "posição horizontal", "y": "posição vertical"}, "confirmar": False},
    "digitar": {"funcao": digitar, "descricao": "Digitar texto", "args": {"texto": "texto a digitar", "enter": "opcional, pressionar Enter (booleano)"}, "confirmar": False},
    "teclas": {"funcao": teclas, "descricao": "Pressionar atalho", "args": {"combinacao": "teclas separadas por +"}, "confirmar": False},
    "rolar": {"funcao": rolar, "descricao": "Rolar a tela", "args": {"quantidade": "inteiro positivo sobe, negativo desce"}, "confirmar": False},
    "janelas": {"funcao": janelas, "descricao": "Listar janelas", "args": {}, "confirmar": False},
    "focar_janela": {"funcao": focar_janela, "descricao": "Focar janela pelo título", "args": {"titulo": "parte do título"}, "confirmar": False},
    "comando": {"funcao": comando, "descricao": "Executar PowerShell", "args": {"powershell": "comando; fora da leitura segura requer confirmação"}, "confirmar": True},
    "lembrete": {"funcao": lembrete, "descricao": "Agendar lembrete", "args": {"quando": "AAAA-MM-DDTHH:MM", "texto": "texto do lembrete"}, "confirmar": False},
}


# Caminhos que contornariam a validação de `comando`: abrir scripts/instaladores ou
# chamar a caixa Executar / menu do sistema e digitar um comando nela.
EXTENSOES_EXECUTAVEIS = (".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
                         ".wsh", ".msi", ".msp", ".scr", ".reg", ".hta", ".cpl", ".com", ".pif")
ATALHOS_PERIGOSOS = {"win+r", "win+x", "ctrl+shift+enter", "ctrl+alt+t"}
PROGRAMAS_DE_COMANDO = ("cmd", "powershell", "pwsh", "wt", "wscript", "cscript", "mshta",
                        "rundll32", "regsvr32", "reg", "msiexec")


def _abrir_perigoso(alvo):
    alvo = str(alvo or "").strip().strip('"').lower()
    if alvo.startswith(("http://", "https://")):
        return False  # sites abrem no navegador (".com" aqui não é executável)
    nome = Path(alvo).name
    if alvo.endswith(EXTENSOES_EXECUTAVEIS) or Path(nome).stem in PROGRAMAS_DE_COMANDO:
        return True
    # .exe só sem confirmação se for de um local de programas instalados
    if alvo.endswith(".exe") and not alvo.startswith(("c:\\program files", "c:\\windows")):
        return True
    return " " in alvo and not alvo.startswith(("http://", "https://")) and not Path(alvo).exists()


def precisa_confirmar(nome, args) -> bool:
    if not isinstance(nome, str) or nome not in ACOES:
        return True
    if not isinstance(args, dict):
        return True
    if nome == "comando":
        return not comando_seguro(args.get("powershell"))
    if nome == "abrir":
        return _abrir_perigoso(args.get("alvo"))
    if nome == "teclas":
        return str(args.get("combinacao", "")).replace(" ", "").lower() in ATALHOS_PERIGOSOS
    return ACOES[nome]["confirmar"]


def executar(nome, args, pedido="") -> dict:
    try:
        if not isinstance(nome, str) or nome not in ACOES:
            raise ValueError("Ação desconhecida.")
        if not isinstance(args, dict):
            raise ValueError("Argumentos devem ser um objeto.")
        funcao = ACOES[nome]["funcao"]
        # Valida pela assinatura pública antes de chamar a função do catálogo.
        assinatura = inspect.signature(globals()[nome])
        ligados = assinatura.bind(**args)
        for chave, valor in ligados.arguments.items():
            tipo = assinatura.parameters[chave].annotation
            if tipo in (str, int, bool) and type(valor) is not tipo:
                raise ValueError(f"Tipo inválido para {chave}.")
        if nome == "foto_camera" and not any(
            palavra in normalizar(pedido) for palavra in ("camera", "foto", "selfie")
        ):
            raise ValueError("A câmera só pode ser usada quando solicitada no pedido.")
        resultado = funcao(**args)
        if resultado == OCUPADO:
            return {"ok": False, "texto": OCUPADO, "imagem": None}
        imagem = str(resultado) if nome in ("ver_tela", "foto_camera") else None
        return {"ok": True, "texto": str(resultado), "imagem": imagem}
    except Exception as erro:
        return {"ok": False, "texto": str(erro), "imagem": None}


def descrever_acoes() -> str:
    return "\n".join(
        f"{nome}({', '.join(f'{arg}: {desc}' for arg, desc in acao['args'].items())}): "
        f"{acao['descricao']}" + (" [requer confirmação]" if acao["confirmar"] else "")
        for nome, acao in ACOES.items()
    )
