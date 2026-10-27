"""Estatísticas locais do reconhecimento e do ritmo da fala."""

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import os
import tempfile

import config

BANCO = Path(__file__).resolve().parent / "secretario.db"
COFRE = Path.home() / "Documents" / "Secretario"
PALAVRAS_COMUNS = set("""
a o as os um uma uns umas de da do das dos em no na nos nas por para com sem sob sobre
e ou mas porque que se como quando onde quem qual quais quanto quanta quantos quantas
eu tu ele ela nós nos vos vós eles elas você vocês meu minha meus minhas teu tua seus
seu sua suas nosso nossa nossos nossas esse essa esses essas este esta estes estas
isso isto aquilo aquele aquela aqueles aquelas aqui ali lá cá agora hoje ontem amanhã
sempre nunca já ainda só também muito muita muitos muitas pouco pouca poucos poucas
mais menos bem mal sim não talvez até então depois antes durante entre desde contra
ser estar ter haver fazer ir vir ver dar dizer poder querer saber ficar achar deixar
falar ouvir abrir fechar usar buscar procurar colocar tirar pegar levar trazer passar
sou é somos são era eram fui foi foram será serão estou está estamos estão estava
estavam tenho tem temos têm tinha tinham vou vai vamos vão fui pode podem quero quer
queremos preciso precisa sei sabe faz fazem fez feito fazer seja seja estar está
dia dias noite noites tarde manhã hora horas minuto minutos segundo segundos tempo
ano anos mês meses semana semanas vez vezes coisa coisas pessoa pessoas gente homem
mulher filho filha pai mãe amigo amiga casa rua cidade país mundo vida trabalho escola
livro texto palavra palavras frase nome número valor dinheiro conta água comida café
porta janela mesa cadeira carro ônibus trem caminho lugar lado parte ponto caso modo
forma tipo exemplo problema pergunta resposta ideia informação notícia história verdade
razão direito fim início meio último primeira primeiro novo nova bom boa grande pequeno
melhor pior certo certa errado errada fácil difícil possível importante necessário
outro outra outros outras todo toda todos todas algum alguma alguns algumas nenhum
nenhuma cada tanto tanta mesmo mesma próprio própria tal apenas bastante quase logo
assim realmente exatamente claro favor obrigado obrigada oi olá tchau pronto beleza
abre abra manda mande mostra mostre veja olha pesquise pesquisa escreve escreva lê leia
salva salve apaga apague cancela cancelar espera espere continua continue volta volte
link links gemas gema arquivo arquivos pasta pastas tela botão programa aplicativo
computador celular internet mensagem mensagens voz áudio vídeo foto imagem música
reunião agenda compromisso lembrete lista tarefa tarefas ajuda ajudar entender explicar
português inglês espanhol francês alemão brasileiro duas dois três quatro cinco seis
sete oito nove dez zero cento mil milhão metade inteiro maior menor perto longe frente
atrás dentro fora cima baixo junto separado rápido devagar cedo tarde suficiente
""".split())


def _normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.casefold())
                   if unicodedata.category(c) != 'Mn')


PALAVRAS_COMUNS = {_normalizar(p) for p in PALAVRAS_COMUNS}


@contextmanager
def _conectar(banco):
    conexao = sqlite3.connect(banco, timeout=30)
    try:
        conexao.executescript('''
            CREATE TABLE IF NOT EXISTS falas (
                ts TEXT, texto TEXT, duvidosas TEXT, pausa_max_interna REAL);
            CREATE TABLE IF NOT EXISTS correcoes_fala (
                ouvido TEXT, correto TEXT, vezes INTEGER, PRIMARY KEY (ouvido, correto));
        ''')
        with conexao:
            yield conexao
    finally:
        conexao.close()


def aprender_pronuncia(ouvido, correto):
    import vocabulario
    palavras = re.findall(r'\w+', ouvido)
    if not palavras or not correto.strip():
        return False
    if len(palavras) == 1 and _normalizar(palavras[0]) in PALAVRAS_COMUNS:
        return False
    vocabulario.aprender_correcao(ouvido, correto)
    return True


def registrar_correcao(ouvido, correto, banco=None):
    with _conectar(banco or BANCO) as conexao:
        conexao.execute('''INSERT INTO correcoes_fala VALUES (?, ?, 1)
            ON CONFLICT(ouvido, correto) DO UPDATE SET vezes=vezes+1''', (ouvido, correto))


def _p90(valores):
    valores = sorted(v for v in valores if v > 0 and math.isfinite(v))
    return valores[math.ceil(len(valores) * .9) - 1] if valores else 0


def pausa_adaptativa(pausa):
    return max(1.0, min(2.2, pausa + .3))


def ajustar_pausa(pausa):
    arquivo = config.BASE / 'config.json'
    dados = json.loads(arquivo.read_text(encoding='utf-8')) if arquivo.exists() else {}
    if dados.get('pausa_auto', config.PADROES['pausa_auto']) is not True:
        return
    dados['pausa_fala'] = pausa_adaptativa(pausa)
    descritor, nome = tempfile.mkstemp(dir=arquivo.parent, suffix='.tmp')
    try:
        with os.fdopen(descritor, 'w', encoding='utf-8') as saida:
            json.dump(dados, saida, ensure_ascii=False, indent=2)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(nome, arquivo)
    finally:
        Path(nome).unlink(missing_ok=True)


def duvidosas(palavras, termos=()):
    """Palavras com baixa confiança, exceto termos do vocabulário: o reforço (hotwords) e a
    correção deixam "LinkedIn"/"Gemma" com probabilidade baixa mesmo quando estão certos."""
    conhecidos = {_normalizar(t) for t in termos}
    return [p['palavra'] for p in palavras if p['prob'] < .5
            and _normalizar(re.sub(r'[^\w-]', '', p['palavra'])) not in conhecidos]


def registrar_fala(texto, palavras, pausas, banco=None, cofre=COFRE, termos=()):
    if not texto.strip():
        return
    banco = banco or BANCO
    incertas = duvidosas(palavras, termos)
    with _conectar(banco) as conexao:
        conexao.execute('INSERT INTO falas VALUES (?, ?, ?, ?)',
                        (datetime.now().isoformat(), texto, json.dumps(incertas),
                         max((p for p in pausas if math.isfinite(p) and p > 0), default=0)))
        total = conexao.execute('SELECT count(*) FROM falas').fetchone()[0]
    if total % 30 == 0 and config.carregar().get('pausa_auto') is True:
        ajustar_pausa(resumo(banco)['pausa_p90'])
    nota = Path(cofre) / 'Perfil' / 'Fala.md'
    if total % 50 == 0 or not nota.exists() or datetime.fromtimestamp(nota.stat().st_mtime).date() != datetime.now().date():
        atualizar_nota(cofre, banco)


def resumo(banco=None):
    contagem = Counter()
    expressoes = Counter()
    with _conectar(banco or BANCO) as conexao:
        falas = conexao.execute('SELECT texto, pausa_max_interna FROM falas').fetchall()
        correcoes = conexao.execute('SELECT ouvido, correto, vezes FROM correcoes_fala ORDER BY vezes DESC LIMIT 20').fetchall()
    for texto, _ in falas:
        palavras = re.findall(r'[^\W\d_]+', _normalizar(texto))
        contagem.update(p for p in palavras
                        if len(p) > 2 and p not in PALAVRAS_COMUNS)
        if len(palavras) > 2:
            expressoes.update(' '.join((a, b)) for a, b in zip(palavras, palavras[1:])
                              if a not in PALAVRAS_COMUNS and b not in PALAVRAS_COMUNS)
    return {'palavras': contagem.most_common(20), 'correcoes': correcoes,
            'expressoes': [(p, n) for p, n in expressoes.most_common(20) if n >= 3],
            'pausa_p90': _p90([p for _, p in falas])}


def atualizar_nota(cofre=COFRE, banco=None):
    dados = resumo(banco)
    linhas = ['# Fala', '', '## Palavras frequentes']
    linhas += [f'- {p}: {n}' for p, n in dados['palavras'] if n >= 2]
    linhas += ['', '## Expressões frequentes']
    linhas += [f'- {p}: {n}' for p, n in dados['expressoes']]
    linhas += ['', '## Termos corrigidos']
    # Só termos curtos: nunca transportar pedidos ou frases inteiras ao cofre.
    for ouvido, correto, vezes in dados['correcoes']:
        if all(0 < len(t) <= 60 and len(t.split()) <= 3 and '\n' not in t and '\r' not in t
               for t in (ouvido, correto)):
            linhas.append(f'- {ouvido} → {correto}: {vezes}')
    linhas += ['', f"Pausa típica (p90): {dados['pausa_p90']:.2f} s.", '']
    nota = Path(cofre) / 'Perfil' / 'Fala.md'
    nota.parent.mkdir(parents=True, exist_ok=True)
    nota.write_text('\n'.join(linhas), encoding='utf-8')


def escolher_idioma(transcrever, idiomas):
    resultado = transcrever('pt')
    # Sem probabilidade (ex.: transcrição na nuvem), fica com o português.
    confianca = resultado.get('prob_idioma')
    if confianca is not None and confianca < .5 and any(i != 'pt' for i in idiomas):
        alternativa = transcrever(None)
        if alternativa['idioma'] in idiomas and (alternativa.get('prob_idioma') or 0) > confianca:
            resultado = alternativa
    return resultado
