"""Trava de segurança do Claude Code: hook PreToolUse que roda antes de cada ferramenta.

As regras "não envie, não pague, não publique sem o sim do Deivid" estão no prompt, mas o
prompt pode falhar (um engano do modelo ou um texto escondido num site). Esta trava é
código: bloqueia de verdade cliques e teclas em botões sensíveis enquanto não houver um
"sim" recente dito ou digitado pelo próprio Deivid, e bloqueia sites de banco sempre.

O "sim" é gravado pelo motor (assistente_voz.py) quando o pedido vem do Deivid; o Claude
não consegue gravá-lo, porque a trava também bloqueia ferramentas que mexam no arquivo.

Uso no hook: python trava.py  (lê o evento JSON do stdin; código 2 bloqueia e o motivo
vai para o Claude pelo stderr).
"""

import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
APROVACAO = BASE / "sinais" / "aprovacao.json"
VALIDADE = 300  # segundos que um "sim" vale

SIM = re.compile(r"^(sim|pode|confirmo|confirma|manda|envia|publica|pode (enviar|mandar|publicar|"
                 r"pagar|confirmar|finalizar|seguir|continuar)|ok,? pode|isso,? pode)\b")
SENSIVEL = re.compile(
    r"\b(enviar|envie|submeter|submit|send|pagar|pague|pagamento|pay|comprar|compre|buy|"
    r"checkout|finalizar|finalize|concluir|confirmar|confirme|confirm|publicar|publique|"
    r"postar|post|publish|share|compartilhar|excluir|exclua|delete|apagar|apague|remover|"
    r"remove|assinar|assine|subscribe|inscrever|candidatar|apply|aceitar|aceito|accept|"
    r"agree|transferir|pix|place order|fazer pedido|criar conta|sign up|cadastrar)\b")
BANCOS = ("itau.com.br", "bradesco.com.br", "santander.com.br", "bb.com.br", "caixa.gov.br",
          "nubank.com.br", "bancointer.com.br", "inter.co", "c6bank.com.br", "btgpactual.com",
          "mercadopago.com.br", "picpay.com", "paypal.com", "sicoob.com.br", "sicredi.com.br",
          "original.com.br", "next.me", "neon.com.br", "pagbank.com.br", "binance.com")
# Preencher campos é liberado (o secretário preenche e para antes de enviar); o que trava é
# o clique ou o aceite que dispara o envio.
CLIQUES = re.compile(r"^mcp__(playwright|chrome)__browser_(click|handle_dialog)$"
                     r"|^mcp__sentidos__acionar$")
NAVEGAR = re.compile(r"^mcp__(playwright|chrome)__browser_(navigate|tabs)$|^mcp__sentidos__abrir$")
INOFENSIVO = re.compile(r"\bcookies?\b")
# Código rodado na página contorna a ferramenta de clique; ele só passa sem "sim" se não
# clicar, enviar formulário nem apertar teclas.
CODIGO = re.compile(r"^mcp__(playwright|chrome)__browser_(run_code_unsafe|evaluate)$")
CODIGO_SENSIVEL = re.compile(r"\.(click|dblclick|tap|submit|requestsubmit|dispatchevent|press)"
                             r"\s*\(|keyboard|mouse")
# Ferramentas que passam pelo hook (o resto nem abre o Python).
MATCHER = r"mcp__playwright__.*|mcp__chrome__.*|mcp__sentidos__.*|Bash|PowerShell|Write|Edit|NotebookEdit"


def _normal(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.,/:-]", " ", texto.lower())).strip()


def registrar_fala(texto, agora=None, arquivo=APROVACAO):
    """Chamado pelo motor com cada pedido do Deivid; um "sim" libera a próxima ação."""
    if not SIM.match(_normal(texto)):
        return False
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps({"ate": (agora or time.time()) + VALIDADE}), encoding="utf-8")
    return True


def aprovado(agora=None, arquivo=APROVACAO):
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))["ate"] > (agora or time.time())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _gastar(arquivo=APROVACAO):
    """Um "sim" vale para uma ação: depois dela, a próxima pede de novo."""
    try:
        arquivo.unlink()
    except OSError:
        pass


def _banco(url):
    host = (urlparse(url if "//" in url else "//" + url).hostname or "").lower()
    return any(host == b or host.endswith("." + b) for b in BANCOS)


def decidir(ferramenta, entrada, agora=None, arquivo=APROVACAO):
    """None libera; um texto é o motivo do bloqueio."""
    entrada = entrada if isinstance(entrada, dict) else {}
    bruto = json.dumps(entrada, ensure_ascii=False).lower()
    if "aprovacao" in bruto and ferramenta not in ("Read", "Glob", "Grep"):
        return "A trava de segurança não pode ser alterada pelo secretário."
    if NAVEGAR.match(ferramenta):
        url = str(entrada.get("url") or entrada.get("alvo") or entrada.get("caminho") or "")
        if url and _banco(url):
            return ("Sites de banco e finanças são bloqueados para o secretário. "
                    "Diga ao Deivid que essa parte é com ele.")
        return None
    if CODIGO.match(ferramenta):
        if not CODIGO_SENSIVEL.search(bruto):
            return None
    elif not CLIQUES.match(ferramenta):
        return None
    elif ferramenta.endswith("handle_dialog"):
        # Aceitar um diálogo do navegador costuma confirmar algo ("Tem certeza que deseja…").
        if not entrada.get("accept"):
            return None
    else:
        alvo = _normal(f"{entrada.get('element', '')} {entrada.get('alvo', '')}")
        if not SENSIVEL.search(alvo) or INOFENSIVO.search(alvo):
            return None
    if aprovado(agora, arquivo):
        _gastar(arquivo)
        return None
    return ("Ação sensível bloqueada pela trava de segurança (enviar, pagar, publicar, "
            "confirmar ou apagar). Mostre ao Deivid o que vai ser feito e pergunte se pode. "
            "Só depois que ELE disser \"sim\" a ação é liberada; repetir sem isso não adianta.")


def principal(entrada=sys.stdin, erro=sys.stderr):
    try:
        evento = json.load(entrada)
    except ValueError:
        return 0
    motivo = decidir(evento.get("tool_name", ""), evento.get("tool_input"))
    if motivo:
        try:
            import registro
            registro.evento("Trava", f"{evento.get('tool_name')}: {motivo[:80]}")
        except Exception:
            pass
        print(motivo, file=erro)
        return 2
    return 0


def configuracao_hook(python=sys.executable):
    """JSON para o --settings do claude -p: só as sessões do secretário usam a trava."""
    comando = f'"{Path(python).as_posix()}" "{Path(__file__).resolve().as_posix()}"'
    return json.dumps({"hooks": {"PreToolUse": [
        {"matcher": MATCHER, "hooks": [{"type": "command", "command": comando, "timeout": 10}]}]}})


if __name__ == "__main__":
    sys.exit(principal())
