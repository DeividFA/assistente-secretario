"""Vocabulário pessoal e correções do reconhecimento de voz."""

import json
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

COFRE = Path.home() / "Documents" / "Secretario"
CORRECOES = Path(__file__).resolve().parent / "correcoes.json"
FIXOS = ["Deivid", "Secretário", "Claude", "Gemma", "Codex", "Gemini", "Grok", "Obsidian"]
_trava = threading.RLock()


def termos(cofre=COFRE, limite=60):
    from comum import normalizar

    cofre = Path(cofre)
    try:
        indice = json.loads((cofre / ".secretario" / "indice.json").read_text(encoding="utf-8"))
        notas = indice.get("notas", [])
    except (OSError, ValueError):
        notas = []

    def atualizado(nota):
        try:
            return (cofre / nota.get("caminho", "")).stat().st_mtime
        except OSError:
            return 0

    nomes = list(FIXOS)
    for nota in sorted(notas, key=atualizado, reverse=True):
        nomes.append(nota.get("titulo", ""))
        aliases = nota.get("aliases", [])
        nomes.extend(aliases if isinstance(aliases, list) else [aliases])
    resultado, vistos = [], set()
    for nome in nomes:
        if not isinstance(nome, str):
            continue
        chave = normalizar(nome)
        if chave and chave not in vistos:
            vistos.add(chave)
            resultado.append(nome.strip())
    return resultado[:max(0, limite)]


def _ler_correcoes():
    try:
        with CORRECOES.open("x", encoding="utf-8") as arquivo:
            json.dump({"gloco de notas": "bloco de notas", "cloud": "Claude",
                       "David": "Deivid"}, arquivo, ensure_ascii=False, indent=2)
    except FileExistsError:
        pass
    dados = json.loads(CORRECOES.read_text(encoding="utf-8"))
    return dados if isinstance(dados, dict) else {}


def corrigir(texto):
    with _trava:
        try:
            pares = _ler_correcoes()
        except (OSError, ValueError):
            return texto
    pares = {errado.casefold(): certo for errado, certo in pares.items()
             if errado.strip() and isinstance(certo, str)}
    if not pares:
        return texto
    padrao = r"(?<!\w)(?:" + "|".join(re.escape(p) for p in sorted(pares, key=len, reverse=True)) + r")(?!\w)"
    return re.sub(padrao, lambda m: pares[m.group().casefold()], texto, flags=re.I)


def aprender_correcao(errado, certo):
    from comum import normalizar

    errado = normalizar(errado)
    certo = certo.strip()
    if not errado or not certo:
        return
    with _trava:
        pares = {normalizar(k): v for k, v in _ler_correcoes().items()}
        pares[errado] = certo
        temporario = CORRECOES.with_suffix(".json.tmp")
        temporario.write_text(json.dumps(pares, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(CORRECOES)


def ativacao_tolerante(texto):
    """Retorna o trecho de ativação nas duas primeiras palavras, ou None."""
    from comum import normalizar

    palavras = list(re.finditer(r"\w+", texto))[:3]
    for i, palavra in enumerate(palavras[:2]):
        candidatos = [palavra]
        if i + 1 < len(palavras) and re.fullmatch(r"\s+", texto[palavra.end():palavras[i + 1].start()]):
            candidatos.append(re.match(r"\w+\s+\w+", texto[palavra.start():]))
        for candidato in candidatos:
            nome = normalizar(candidato.group()).replace(" ", "")
            if nome.startswith("secretariado"):
                continue
            anterior = list(range(len("secretario") + 1))
            for letra in nome:
                linha = [anterior[0] + 1]
                for j, alvo in enumerate("secretario", 1):
                    linha.append(min(linha[-1] + 1, anterior[j] + 1,
                                     anterior[j - 1] + (letra != alvo)))
                anterior = linha
            if anterior[-1] <= 2 and SequenceMatcher(None, nome, "secretario").ratio() >= 0.8:
                return re.compile(r"[\s\S]{%d}[\s,.!?:;-]*" % len(candidato.group())).match(texto, palavra.start())
    return None
