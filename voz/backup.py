"""Cópias verificadas do banco e dos dados locais."""

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager, closing
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import config
import memoria
import registro

ARQUIVOS = ("config.json", "correcoes.json", "lembretes.json", "motor.txt")
BASE = Path(__file__).resolve().parent


@contextmanager
def _trava(nome):
    """Trava entre processos; o sistema libera ao encerrar o processo."""
    caminho = Path(registro.BANCO).parent / nome
    with caminho.open("a+b") as arquivo:
        arquivo.seek(0, 2)
        if arquivo.tell() == 0:
            arquivo.write(b"0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            arquivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(arquivo, fcntl.LOCK_UN)


def motor_ativo():
    """Mantém a trava que impede restaurar durante o uso do motor."""
    return _trava(".motor-backup.lock")


def _pastas():
    opcoes = config.carregar()
    pastas = [Path(opcoes["pasta_backup"]).expanduser().resolve()]
    if opcoes.get("pasta_backup_extra"):
        extra = Path(opcoes["pasta_backup_extra"]).expanduser().resolve()
        if extra not in pastas:
            pastas.append(extra)
    for pasta in pastas:
        if pasta == memoria.COFRE.resolve() or memoria.COFRE.resolve() in pasta.parents:
            raise ValueError("A pasta de backup deve ficar fora do cofre.")
    return pastas


def verificar_banco(banco=None):
    """Confere o banco sem criar arquivos nem alterar seu conteúdo."""
    caminho = Path(banco if banco is not None else registro.BANCO)
    try:
        with closing(sqlite3.connect(caminho.resolve().as_uri() + "?mode=ro", uri=True)) as conexao:
            return "\n".join(linha[0] for linha in conexao.execute("PRAGMA integrity_check"))
    except sqlite3.Error as erro:
        return str(erro)


def _resumo(caminho):
    soma = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            soma.update(bloco)
    return {"sha256": soma.hexdigest(), "tamanho": caminho.stat().st_size}


def _validar(pasta):
    manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    esperados = set(manifesto["arquivos"])
    if not {"secretario.db", "cofre.zip"} <= esperados or not esperados <= set(ARQUIVOS) | {"secretario.db", "cofre.zip"}:
        raise ValueError("Manifesto inválido.")
    for nome, resumo in manifesto["arquivos"].items():
        if _resumo(pasta / nome) != resumo:
            raise ValueError(f"Arquivo de backup alterado: {nome}")
    if verificar_banco(pasta / "secretario.db") != "ok":
        raise ValueError("Banco do backup não está íntegro.")
    return manifesto


def listar_backups():
    """Lista cópias completas das duas pastas, mais recentes primeiro."""
    encontrados = []
    for raiz in _pastas():
        if not raiz.exists():
            continue
        for pasta in raiz.iterdir():
            if pasta.is_dir() and not pasta.name.startswith("."):
                try:
                    dados = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
                    datetime.fromisoformat(dados["criado"])
                    encontrados.append({"nome": pasta.name, "caminho": str(pasta),
                                        "criado": dados["criado"], "motivo": dados["motivo"]})
                except (OSError, ValueError, KeyError, TypeError):
                    continue
    return sorted(encontrados, key=lambda item: item["criado"], reverse=True)


def _rotacionar(agora):
    for raiz in _pastas():
        grupos = [set(), set(), set()]
        for item in listar_backups():
            pasta = Path(item["caminho"])
            if pasta.parent != raiz:
                continue
            data = datetime.fromisoformat(item["criado"])
            if item["motivo"] in ("antes_reparo", "antes_restaurar"):
                manter = agora - data <= timedelta(days=30)
            else:
                chaves = (data.date(), data.isocalendar()[:2], (data.year, data.month))
                manter = False
                for grupo, chave, limite in zip(grupos, chaves, (7, 4, 6)):
                    if chave not in grupo and len(grupo) < limite:
                        grupo.add(chave)
                        manter = True
            if not manter:
                shutil.rmtree(pasta)


def fazer_backup(motivo):
    """Publica uma cópia consistente, com manifesto, nas pastas configuradas."""
    if not re.fullmatch(r"[a-z0-9_]{1,40}", motivo):
        raise ValueError("Motivo inválido.")
    with _trava(".backup.lock"):
        agora = datetime.now()
        nome = f"{agora:%Y-%m-%d_%H%M%S}_{motivo}"
        pastas = _pastas()
        destinos = [raiz / nome for raiz in pastas]
        if any(destino.exists() for destino in destinos):
            raise FileExistsError("Já existe um backup com esse nome neste segundo.")
        pastas[0].mkdir(parents=True, exist_ok=True)
        publicadas = []
        try:
            with tempfile.TemporaryDirectory(prefix=".backup-", dir=pastas[0]) as temporaria:
                pasta = Path(temporaria)
                origem = Path(registro.BANCO).resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(origem, uri=True)) as entrada:
                    with closing(sqlite3.connect(pasta / "secretario.db")) as saida:
                        entrada.backup(saida)
                        saida.execute("PRAGMA journal_mode=DELETE")
                        tabelas = [linha[0] for linha in saida.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'")]
                        linhas = {t: saida.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0]
                                  for t in tabelas}
                integridade = verificar_banco(pasta / "secretario.db")
                if integridade != "ok":
                    raise ValueError(f"Backup sem integridade: {integridade}")
                for arquivo in ARQUIVOS:
                    if (BASE / arquivo).is_file():
                        shutil.copy2(BASE / arquivo, pasta / arquivo)
                with ZipFile(pasta / "cofre.zip", "w", ZIP_DEFLATED) as arquivo:
                    for nota in sorted(memoria.COFRE.rglob("*")):
                        relativo = nota.relative_to(memoria.COFRE)
                        if nota.is_file() and not (relativo.parts[0] == ".obsidian" and nota.name.startswith("workspace")):
                            arquivo.write(nota, relativo.as_posix())
                manifesto = {"criado": agora.isoformat(), "motivo": motivo,
                             "integridade": integridade, "linhas_por_tabela": linhas,
                             "chaves_api": "Gerenciador de Credenciais do Windows; não incluídas",
                             "arquivos": {p.name: _resumo(p) for p in pasta.iterdir()}}
                (pasta / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
                for destino in destinos:
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    publicadas.append(destino)
                    shutil.copytree(pasta, destino)
                    _validar(destino)
        except Exception:
            for destino in publicadas:
                if destino.exists():
                    shutil.rmtree(destino)
            raise
        _rotacionar(agora)
        return str(destinos[0])


def backup_diario():
    """Cria a cópia inicial quando a última íntegra tem mais de 24 horas."""
    ultimo = ultimo_backup_integro()
    if ultimo and datetime.now() - datetime.fromisoformat(ultimo["criado"]) <= timedelta(hours=24):
        return None
    return fazer_backup("diario")


def ultimo_backup_integro():
    """Encontra a cópia íntegra mais recente, incluindo a pasta extra."""
    for item in listar_backups():
        try:
            _validar(Path(item["caminho"]))
        except (OSError, ValueError, KeyError):
            continue
        return item
    return None


def restaurar(nome, confirmado=False, pelo_motor=False):
    """Restaura uma cópia verificada com aprovação explícita. Outros processos só restauram
    com o motor parado; o próprio motor (que segura a trava) passa pelo_motor=True."""
    if confirmado is not True:
        raise ValueError("A restauração exige confirmação do Deivid.")
    if Path(nome).name != nome or nome in (".", ".."):
        raise ValueError("Nome de backup inválido.")
    with (contextlib.nullcontext() if pelo_motor else motor_ativo()):
        candidatos = [Path(item["caminho"]) for item in listar_backups() if item["nome"] == nome]
        pasta = None
        for candidato in candidatos:
            try:
                _validar(candidato)
                pasta = candidato
                break
            except (OSError, ValueError, KeyError):
                continue
        if pasta is None:
            raise ValueError("Backup íntegro não encontrado.")
        with tempfile.TemporaryDirectory(prefix=".restaurar-", dir=Path(registro.BANCO).parent) as temporaria:
            preparo = Path(temporaria)
            shutil.copytree(pasta, preparo / "copia")
            pasta = preparo / "copia"
            _validar(pasta)
            cofre = preparo / "cofre"
            cofre.mkdir()
            with ZipFile(pasta / "cofre.zip") as arquivo:
                for info in arquivo.infolist():
                    alvo = (cofre / info.filename).resolve()
                    if cofre.resolve() not in alvo.parents:
                        raise ValueError("Caminho inválido no cofre.zip.")
                arquivo.extractall(cofre)
            try:
                seguranca = fazer_backup("antes_restaurar")
            except (sqlite3.Error, ValueError):
                if verificar_banco() == "ok":
                    raise
                # Banco corrompido não pode produzir uma cópia íntegra.
                seguranca = None
            with _trava(".backup.lock"):
                if seguranca is None:
                    shutil.copy2(pasta / "secretario.db", preparo / "restaurado.db")
                    seguranca = _quarentenar()
                    (preparo / "restaurado.db").replace(registro.BANCO)
                else:
                    # A API também evita reutilizar páginas antigas do WAL.
                    with closing(sqlite3.connect(pasta / "secretario.db")) as entrada:
                        with closing(sqlite3.connect(registro.BANCO)) as saida:
                            entrada.backup(saida)
                for nome_arquivo in ARQUIVOS:
                    alvo = BASE / nome_arquivo
                    if (pasta / nome_arquivo).exists():
                        shutil.copy2(pasta / nome_arquivo, alvo)
                    elif alvo.exists():
                        alvo.unlink()
                # Preserva apenas o estado de janelas excluído da cópia.
                memoria.COFRE.mkdir(parents=True, exist_ok=True)
                for alvo in memoria.COFRE.iterdir():
                    if alvo.name == ".obsidian":
                        for filho in alvo.iterdir():
                            if not filho.name.startswith("workspace"):
                                shutil.rmtree(filho) if filho.is_dir() else filho.unlink()
                    else:
                        shutil.rmtree(alvo) if alvo.is_dir() else alvo.unlink()
                shutil.copytree(cofre, memoria.COFRE, dirs_exist_ok=True)
        return {"texto": "Backup restaurado. Reinicie o secretário.", "seguranca": seguranca}


def _quarentenar():
    """Preserva dados irrecuperáveis sem apresentá-los como backup íntegro."""
    banco = Path(registro.BANCO)
    pasta = Path(tempfile.mkdtemp(prefix=".quarentena-", dir=banco.parent))
    for nome in ARQUIVOS:
        if (BASE / nome).is_file():
            shutil.copy2(BASE / nome, pasta / nome)
    if memoria.COFRE.exists():
        shutil.copytree(memoria.COFRE, pasta / "cofre")
    (pasta / "aviso.txt").write_text(
        "Banco corrompido preservado antes da restauração. Não é um backup íntegro.", encoding="utf-8")
    # Move o original e seus journals; nunca copia diretamente o banco ativo.
    for sufixo in ("", "-wal", "-shm", "-journal"):
        origem = Path(str(banco) + sufixo)
        if origem.exists():
            origem.replace(pasta / origem.name)
    return str(pasta)
