"""Leitura, índice e busca da memória no cofre Obsidian."""

import json
import re
from datetime import date, datetime
from pathlib import Path


COFRE = Path.home() / "Documents" / "Secretario"
ASSUNTOS = (
    "Religião", "Trabalho", "Família", "Finanças", "Saúde", "Tecnologia",
    "Estudos", "Compromissos", "Casa", "Lazer", "Pessoas", "Outros",
)
STOPWORDS = set("para como onde quando porque sobre entre esta este isso esse essa "
                "mais muito pela pelo pelas pelos uma umas uns voce voces dele dela "
                "deles delas nosso nossa nossos nossas qual quais sera tambem fala".split())


def normalizar(texto):
    from comum import normalizar as normalizar_comum
    return " ".join(normalizar_comum(texto).split())


def preparar_cofre(cofre=COFRE):
    cofre = Path(cofre)
    for pasta in ("Assuntos", "Conceitos", ".secretario"):
        (cofre / pasta).mkdir(parents=True, exist_ok=True)
    for assunto in ASSUNTOS:
        caminho = cofre / "Assuntos" / f"{assunto}.md"
        if not caminho.exists():
            caminho.write_text(
                f"---\ntipo: assunto\natualizado: {date.today().isoformat()}\n---\n"
                f"# {assunto}\n\n## Conceitos\n", encoding="utf-8")


def _sem_aspas(valor):
    valor = valor.strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        return valor[1:-1]
    return valor


def _valor(valor):
    valor = valor.strip()
    if valor.startswith("[") and valor.endswith("]"):
        itens = re.findall(r'''"[^"]*"|'[^']*'|[^,]+''', valor[1:-1])
        return [_sem_aspas(item) for item in itens if item.strip()]
    return _sem_aspas(valor)


def ler_nota(caminho):
    caminho = Path(caminho)
    texto = caminho.read_text(encoding="utf-8-sig")
    linhas = texto.splitlines()
    frontmatter = {}
    inicio = 0
    if linhas and linhas[0].strip() == "---":
        fim = next((i for i in range(1, len(linhas)) if linhas[i].strip() == "---"), None)
        if fim is not None:
            chave = None
            for linha in linhas[1:fim]:
                item = re.match(r"^\s*-\s+(.+)$", linha)
                campo = re.match(r"^([\w-]+):\s*(.*)$", linha)
                if item and chave is not None:
                    if not isinstance(frontmatter[chave], list):
                        frontmatter[chave] = []
                    frontmatter[chave].append(_sem_aspas(item[1]))
                elif campo:
                    chave = campo[1]
                    frontmatter[chave] = _valor(campo[2])
            inicio = fim + 1
    corpo = linhas[inicio:]
    titulo = next((i for i, linha in enumerate(corpo) if linha.startswith("# ")), None)
    paragrafo = []
    if titulo is not None:
        for linha in corpo[titulo + 1:]:
            if not linha.strip():
                if paragrafo:
                    break
                continue
            if re.match(r"^\s*(?:#|[-*+]\s|\d+\.\s|>)", linha):
                if paragrafo:
                    break
                continue
            paragrafo.append(linha.strip())
    links = list(dict.fromkeys(alvo.strip() for alvo in
                              re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", texto)))
    return {"titulo": caminho.stem, "frontmatter": frontmatter,
            "links": links, "resumo": " ".join(paragrafo)[:200]}


def indexar(cofre=COFRE):
    cofre = Path(cofre)
    notas = []
    termos = {}
    for caminho in sorted(cofre.rglob("*.md")):
        relativo = caminho.relative_to(cofre)
        if any(parte.startswith(".") or parte == "Modelos" for parte in relativo.parts[:-1]):
            continue
        nota = ler_nota(caminho)
        campos = nota["frontmatter"]
        aliases = campos.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = [aliases] if aliases else []
        assunto = str(campos.get("assunto", ""))
        assunto = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"\1", assunto)
        registro = {"caminho": relativo.as_posix(), "titulo": nota["titulo"],
                    "tipo": campos.get("tipo", ""), "assunto": assunto,
                    "aliases": aliases, "links": nota["links"], "resumo": nota["resumo"]}
        notas.append(registro)
        for nome in [registro["titulo"], *aliases]:
            termo = normalizar(nome)
            destinos = termos.setdefault(termo, []) if termo else []
            if termo and registro["caminho"] not in destinos:
                destinos.append(registro["caminho"])
    indice = {"notas": notas, "termos": termos}
    (cofre / ".secretario").mkdir(parents=True, exist_ok=True)
    (cofre / ".secretario" / "indice.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
    return indice


def _carregar_indice(cofre):
    caminho = Path(cofre) / ".secretario" / "indice.json"
    if not caminho.exists():
        return indexar(cofre)
    return json.loads(caminho.read_text(encoding="utf-8"))


def _buscar(texto, indice, limite):
    texto = normalizar(texto)
    palavras = {p for p in texto.split() if len(p) >= 4 and p not in STOPWORDS}
    pontos = {}
    for nota in indice["notas"]:
        termos = {normalizar(nome) for nome in [nota["titulo"], *nota["aliases"]]}
        total = sum(3 for termo in termos if termo and
                    re.search(r"(?<!\w)" + re.escape(termo) + r"(?!\w)", texto))
        palavras_nota = set(" ".join(termos).split())
        total += len(palavras & palavras_nota)
        if total:
            pontos[nota["caminho"]] = total
    por_caminho = {nota["caminho"]: nota for nota in indice["notas"]}
    destinos = {}
    for nota in indice["notas"]:
        for nome in [nota["titulo"], *nota["aliases"], str(Path(nota["caminho"]).with_suffix("")).replace("\\", "/")]:
            destinos.setdefault(normalizar(nome), set()).add(nota["caminho"])
    acrescimos = {}
    for caminho, total in pontos.items():
        nota = por_caminho[caminho]
        ligados = set()
        if nota["assunto"]:
            hub = f'Assuntos/{nota["assunto"]}.md'
            if hub in por_caminho:
                ligados.add(hub)
        for link in nota["links"]:
            ligados.update(destinos.get(normalizar(link.removesuffix(".md")), ()))
        for destino in ligados - {caminho}:
            acrescimos[destino] = acrescimos.get(destino, 0) + total / 2
    for caminho, total in acrescimos.items():
        pontos[caminho] = pontos.get(caminho, 0) + total
    ordenados = sorted(pontos, key=lambda caminho: (-pontos[caminho], caminho))
    return [{**{chave: por_caminho[caminho][chave] for chave in
                ("caminho", "titulo", "assunto", "resumo")}, "pontos": pontos[caminho]}
            for caminho in ordenados[:max(0, limite)]]


def buscar(texto, cofre=COFRE, limite=5):
    return _buscar(texto, _carregar_indice(cofre), limite)


def contexto(texto, cofre=COFRE, max_chars=1200):
    indice = _carregar_indice(cofre)
    encontradas = _buscar(texto, indice, 5)
    if not encontradas:
        return ""
    por_caminho = {nota["caminho"]: nota for nota in indice["notas"]}
    linhas = ["Memória relevante (cofre Obsidian):"]
    for nota in encontradas:
        assunto = f' [{nota["assunto"]}]' if nota["assunto"] else ""
        resumo = nota["resumo"].rstrip(". ")
        linha = f'- {nota["titulo"]}{assunto}' + (f": {resumo}." if resumo else "")
        links = por_caminho[nota["caminho"]]["links"]
        if links:  # hubs acumulam muitos links; poucos bastam para orientar o modelo
            linha += (" " if resumo else ": ") + "Ligado a: " + ", ".join(links[:5]) + ("…" if len(links) > 5 else "")
        linhas.append(linha)
    return "\n".join(linhas)[:max(0, max_chars)]


def _lista(valor):
    return valor if isinstance(valor, list) else [valor] if valor else []


def _unir(valores):
    resultado = []
    vistos = set()
    for valor in valores:
        valor = str(valor).strip()
        chave = normalizar(valor)
        if chave and chave not in vistos:
            resultado.append(valor)
            vistos.add(chave)
    return resultado


def _nome_conceito(nome):
    nome = " ".join(str(nome).split()).title()
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip(" .")
    if not nome:
        raise ValueError("Nome de conceito vazio")
    return nome


def _campo_nota(texto, chave, valor):
    if not texto.startswith("---\n") or "\n---\n" not in texto[4:]:
        return f"---\n{chave}: {valor}\n---\n" + texto
    fim = texto.index("\n---\n", 4)
    campos = texto[4:fim]
    padrao = rf"(?m)^{re.escape(chave)}:[^\n]*(?:\n[ \t]*- [^\n]*)*"
    if re.search(padrao, campos):
        campos = re.sub(padrao, lambda m: f"{chave}: {valor}", campos)
    else:
        campos += f"\n{chave}: {valor}"
    return "---\n" + campos + texto[fim:]


def _acrescentar_secao(texto, titulo, linhas):
    if not linhas:
        return texto
    cabecalho = re.search(rf"(?m)^## {re.escape(titulo)}\s*$", texto)
    if cabecalho:
        proximo = re.search(r"(?m)^#{1,2} ", texto[cabecalho.end():])
        fim = cabecalho.end() + proximo.start() if proximo else len(texto)
        return texto[:fim].rstrip() + "\n" + "\n".join(linhas) + "\n\n" + texto[fim:]
    return texto.rstrip() + f"\n\n## {titulo}\n" + "\n".join(linhas) + "\n"


def _fatos_existentes(texto):
    return {normalizar(linha) for linha in
            re.findall(r"(?m)^- (?:\d{4}-\d{2}-\d{2} — )?(.+)$", texto)}


def aprender(conhecimento: dict, cofre=COFRE, hoje=None) -> list[str]:
    cofre = Path(cofre)
    dia = (hoje or date.today()).isoformat()
    antes = {p.relative_to(cofre).as_posix(): p.read_bytes()
             for p in cofre.rglob("*.md")}
    preparar_cofre(cofre)

    def salvar(caminho, texto):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if not caminho.exists() or caminho.read_text(encoding="utf-8") != texto:
            caminho.write_text(texto, encoding="utf-8")

    def encontrar(nomes):
        procurados = {normalizar(n) for n in nomes}
        for caminho in sorted((cofre / "Conceitos").rglob("*.md")):
            nota = ler_nota(caminho)
            termos = [nota["titulo"], *_lista(nota["frontmatter"].get("aliases"))]
            if procurados & {normalizar(n) for n in termos}:
                return caminho
        return None

    def garantir_hub(caminho, assunto, resumo):
        hub = cofre / "Assuntos" / f"{assunto}.md"
        texto = hub.read_text(encoding="utf-8")
        if normalizar(caminho.stem) not in {normalizar(n) for n in ler_nota(hub)["links"]}:
            resumo = " ".join(resumo.split())
            texto = _acrescentar_secao(texto, "Conceitos", [
                f"- [[{caminho.stem}]]" + (f" — {resumo}" if resumo else "")])
            salvar(hub, _campo_nota(texto, "atualizado", dia))

    def criar(nome, assunto, resumo=""):
        caminho = cofre / "Conceitos" / f"{_nome_conceito(nome)}.md"
        salvar(caminho, f'---\ntipo: conceito\nassunto: "[[{assunto}]]"\n'
               f'aliases: []\natualizado: {dia}\n---\n# {caminho.stem}\n\n'
               f'{resumo}\n\n## Relacionados\n\n## Das conversas\n')
        return caminho

    for conceito in conhecimento.get("conceitos", []):
        nome = str(conceito["nome"]).strip()
        aliases = _unir(_lista(conceito.get("aliases")))
        assunto = conceito.get("assunto")
        if assunto not in ASSUNTOS:
            assunto = "Outros"
        caminho = encontrar([nome, *aliases])
        if caminho is None:
            caminho = criar(nome, assunto, str(conceito.get("resumo", "")))
        nota = ler_nota(caminho)
        assunto_existente = str(nota["frontmatter"].get("assunto", "")).strip("[]")
        if assunto_existente in ASSUNTOS:
            assunto = assunto_existente
        texto = caminho.read_text(encoding="utf-8-sig")
        aliases = _unir([*_lista(nota["frontmatter"].get("aliases")), *aliases,
                         *([nome] if normalizar(nome) != normalizar(caminho.stem) else [])])
        texto = _campo_nota(texto, "aliases", json.dumps(aliases, ensure_ascii=False))
        texto = _campo_nota(texto, "atualizado", dia)
        salvar(caminho, texto)
        ligados = {normalizar(n) for n in nota["links"]}
        novos = []
        for relacionado in _unir(_lista(conceito.get("relacionados"))):
            destino = encontrar([relacionado])
            if destino is None:
                destino = criar(relacionado, assunto)
            if destino == caminho:
                continue
            nota_destino = ler_nota(destino)
            assunto_destino = str(nota_destino["frontmatter"].get("assunto", "")).strip("[]")
            garantir_hub(destino, assunto_destino if assunto_destino in ASSUNTOS else assunto,
                         nota_destino["resumo"])
            if normalizar(destino.stem) not in ligados:
                novos.append(f"- [[{destino.stem}]]")
                ligados.add(normalizar(destino.stem))
            # ligação de volta: quem pergunta só sobre a Bíblia também chega a Jesus Cristo
            if normalizar(caminho.stem) not in {normalizar(n) for n in nota_destino["links"]}:
                salvar(destino, _acrescentar_secao(destino.read_text(encoding="utf-8"),
                                                   "Relacionados", [f"- [[{caminho.stem}]]"]))
        texto = _acrescentar_secao(texto, "Relacionados", novos)
        fato = " ".join(str(conceito.get("fato", "")).split())
        if fato and normalizar(fato) not in _fatos_existentes(texto):
            texto = _acrescentar_secao(texto, "Das conversas", [f"- {dia} — {fato}"])
        salvar(caminho, texto)
        garantir_hub(caminho, assunto, nota["resumo"])

    perfil = cofre / "Perfil" / "Aprendizados.md"
    texto = perfil.read_text(encoding="utf-8") if perfil.exists() else "# Aprendizados\n"
    fatos = _fatos_existentes(texto)
    for fato in conhecimento.get("fatos_usuario", []):
        fato = " ".join(str(fato).split())
        if fato and normalizar(fato) not in fatos:
            texto = texto.rstrip() + f"\n- {dia} — {fato}\n"
            fatos.add(normalizar(fato))
    if fatos:
        salvar(perfil, texto)
    indexar(cofre)
    return sorted(p.relative_to(cofre).as_posix() for p in cofre.rglob("*.md")
                  if antes.get(p.relative_to(cofre).as_posix()) != p.read_bytes())


def registrar_diario(pergunta, resposta, cofre=COFRE, agora=None):
    agora = agora or datetime.now()
    dia = agora.date().isoformat()
    caminho = Path(cofre) / "Diário" / f"{dia}.md"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        caminho.write_text(f"# {dia}\n\n", encoding="utf-8")
    pergunta = " ".join(str(pergunta).split())[:300]
    resposta = " ".join(str(resposta).split())[:300]
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(f'- {agora:%H:%M} — **Você:** {pergunta} → **Secretário:** {resposta}\n')
