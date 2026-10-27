"""Testes de backup sem acessar o banco ou o cofre reais."""

import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    base = tmp_path / "voz"
    base.mkdir()
    banco = base / "secretario.db"
    with closing(sqlite3.connect(banco)) as conexao:
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("CREATE TABLE dados (id INTEGER PRIMARY KEY, texto TEXT)")
        conexao.execute("INSERT INTO dados (texto) VALUES ('original')")
        conexao.commit()
    cofre = tmp_path / "cofre"
    (cofre / ".obsidian").mkdir(parents=True)
    (cofre / "nota.md").write_text("Memória original", encoding="utf-8")
    (cofre / ".obsidian" / "workspace.json").write_text("estado", encoding="utf-8")
    (cofre / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (base / "config.json").write_text('{"microfone": null}', encoding="utf-8")
    (base / "motor.txt").write_text("claude", encoding="utf-8")
    opcoes = {"pasta_backup": str(tmp_path / "backups"),
              "pasta_backup_extra": str(tmp_path / "extra")}
    monkeypatch.setattr(backup, "BASE", base)
    monkeypatch.setattr(backup.registro, "BANCO", banco)
    monkeypatch.setattr(backup.memoria, "COFRE", cofre)
    monkeypatch.setattr(backup.config, "carregar", lambda: opcoes.copy())
    return base, banco, cofre, opcoes


def test_backup_wal_concorrente_e_manifesto(ambiente):
    base, banco, cofre, opcoes = ambiente
    parar = threading.Event()
    pronto = threading.Event()
    erros = []

    def escrever():
        try:
            with closing(sqlite3.connect(banco, timeout=10)) as conexao:
                conexao.execute("PRAGMA wal_autocheckpoint=0")
                while not parar.is_set():
                    conexao.execute("INSERT INTO dados (texto) VALUES ('concorrente')")
                    conexao.commit()
                    pronto.set()
                    parar.wait(0.002)
        except Exception as erro:
            erros.append(erro)
            pronto.set()

    thread = threading.Thread(target=escrever)
    thread.start()
    try:
        assert pronto.wait(5)
        assert not erros
        assert Path(str(banco) + "-wal").exists()
        pasta = Path(backup.fazer_backup("pedido"))
    finally:
        parar.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert not erros
    manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["integridade"] == "ok"
    assert "não incluídas" in manifesto["chaves_api"]
    with closing(sqlite3.connect(pasta / "secretario.db")) as copia:
        total = copia.execute("SELECT count(*) FROM dados").fetchone()[0]
        assert copia.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert total >= 2
    assert manifesto["linhas_por_tabela"] == {"dados": total}
    assert set(manifesto["arquivos"]) == {"secretario.db", "cofre.zip", "config.json", "motor.txt"}
    for nome, resumo in manifesto["arquivos"].items():
        conteudo = (pasta / nome).read_bytes()
        assert resumo == {"sha256": hashlib.sha256(conteudo).hexdigest(), "tamanho": len(conteudo)}
        assert conteudo == (Path(opcoes["pasta_backup_extra"]) / pasta.name / nome).read_bytes()
    with ZipFile(pasta / "cofre.zip") as arquivo:
        assert set(arquivo.namelist()) == {"nota.md", ".obsidian/app.json"}


def test_integridade_falha_remove_tudo(ambiente, monkeypatch):
    monkeypatch.setattr(backup, "verificar_banco", lambda banco=None: "corrompido")
    with pytest.raises(ValueError, match="integridade"):
        backup.fazer_backup("pedido")
    for raiz in backup._pastas():
        assert not raiz.exists() or not list(raiz.iterdir())


def test_falha_destino_extra_remove_publicacao(ambiente, monkeypatch):
    copiar = backup.shutil.copytree
    extra = Path(ambiente[3]["pasta_backup_extra"])

    def falhar(origem, destino, **opcoes):
        if Path(destino).parent == extra:
            Path(destino).mkdir()
            raise OSError("Destino indisponível")
        return copiar(origem, destino, **opcoes)

    monkeypatch.setattr(backup.shutil, "copytree", falhar)
    with pytest.raises(OSError, match="indisponível"):
        backup.fazer_backup("pedido")
    assert all(not list(pasta.iterdir()) for pasta in backup._pastas())


def test_rotacao_datas_falsas(ambiente):
    agora = datetime(2026, 10, 27, 12)
    raiz = backup._pastas()[0]
    raiz.mkdir()
    for dias in range(240):
        data = agora - timedelta(days=dias)
        pasta = raiz / f"{data:%Y-%m-%d_%H%M%S}_diario"
        pasta.mkdir()
        (pasta / "manifesto.json").write_text(json.dumps({
            "criado": data.isoformat(), "motivo": "diario"}), encoding="utf-8")
    for dias in (29, 31):
        data = agora - timedelta(days=dias)
        pasta = raiz / f"{data:%Y-%m-%d_%H%M%S}_antes_reparo"
        pasta.mkdir()
        (pasta / "manifesto.json").write_text(json.dumps({
            "criado": data.isoformat(), "motivo": "antes_reparo"}), encoding="utf-8")
    backup._rotacionar(agora)
    restantes = backup.listar_backups()
    comuns = [datetime.fromisoformat(item["criado"]) for item in restantes if item["motivo"] == "diario"]
    esperadas = {agora - timedelta(days=dias) for dias in range(7)}
    semanas = set()
    meses = set()
    for dias in range(240):
        data = agora - timedelta(days=dias)
        semana = data.isocalendar()[:2]
        mes = (data.year, data.month)
        if semana not in semanas and len(semanas) < 4:
            semanas.add(semana)
            esperadas.add(data)
        if mes not in meses and len(meses) < 6:
            meses.add(mes)
            esperadas.add(data)
    assert set(comuns) == esperadas
    reparos = [item for item in restantes if item["motivo"] == "antes_reparo"]
    assert len(reparos) == 1
    assert datetime.fromisoformat(reparos[0]["criado"]) == agora - timedelta(days=29)


def test_restauracao_confirma_e_salva_antes(ambiente):
    base, banco, cofre, opcoes = ambiente
    pasta = Path(backup.fazer_backup("pedido"))
    with closing(sqlite3.connect(banco)) as conexao:
        conexao.execute("UPDATE dados SET texto='alterado'")
        conexao.commit()
    (cofre / "nota.md").write_text("Alterado", encoding="utf-8")
    (cofre / "nova.md").write_text("Nova", encoding="utf-8")
    (base / "motor.txt").write_text("gpt", encoding="utf-8")
    (base / "lembretes.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="confirmação"):
        backup.restaurar(pasta.name)
    resultado = backup.restaurar(pasta.name, confirmado=True)
    assert "Reinicie" in resultado["texto"]
    seguranca = Path(resultado["seguranca"])
    with closing(sqlite3.connect(seguranca / "secretario.db")) as copia:
        assert copia.execute("SELECT texto FROM dados").fetchone()[0] == "alterado"
    with closing(sqlite3.connect(banco)) as conexao:
        assert conexao.execute("SELECT texto FROM dados").fetchone()[0] == "original"
    assert (cofre / "nota.md").read_text(encoding="utf-8") == "Memória original"
    assert not (cofre / "nova.md").exists()
    assert (cofre / ".obsidian" / "workspace.json").read_text(encoding="utf-8") == "estado"
    assert (base / "motor.txt").read_text(encoding="utf-8") == "claude"
    assert not (base / "lembretes.json").exists()


def test_motor_ativo_impede_restauracao(ambiente):
    pasta = Path(backup.fazer_backup("pedido"))
    with backup.motor_ativo():
        with pytest.raises(OSError):
            backup.restaurar(pasta.name, confirmado=True)


def test_motor_restaura_com_a_propria_trava(ambiente):
    pasta = Path(backup.fazer_backup("pedido"))
    with backup.motor_ativo():
        resultado = backup.restaurar(pasta.name, confirmado=True, pelo_motor=True)
    assert resultado["seguranca"]
    assert backup.verificar_banco() == "ok"


def test_backup_adulterado_nao_restaurado(ambiente):
    pasta = Path(backup.fazer_backup("pedido"))
    # Adultera ambas as cópias.
    for raiz in backup._pastas():
        (raiz / pasta.name / "motor.txt").write_text("adulterado", encoding="utf-8")
    with pytest.raises(ValueError, match="íntegro"):
        backup.restaurar(pasta.name, confirmado=True)


def test_banco_ausente_nao_e_criado(ambiente):
    caminho = ambiente[0] / "ausente.db"
    assert backup.verificar_banco(caminho) != "ok"
    assert not caminho.exists()


def test_diario_reutiliza_backup_recente(ambiente, monkeypatch):
    backup.fazer_backup("pedido")

    def inesperado(motivo):
        pytest.fail("Não deveria criar outra cópia em menos de 24 horas")

    monkeypatch.setattr(backup, "fazer_backup", inesperado)
    assert backup.backup_diario() is None


def test_rejeita_destino_dentro_do_cofre(ambiente, monkeypatch):
    monkeypatch.setattr(backup.config, "carregar", lambda: {
        "pasta_backup": str(ambiente[2] / "backups")})
    with pytest.raises(ValueError, match="fora do cofre"):
        backup.fazer_backup("pedido")


def test_diario_cria_quando_antigo(ambiente, monkeypatch):
    pasta = Path(backup.fazer_backup("pedido"))
    antigo = (datetime.now() - timedelta(hours=25)).isoformat()
    for raiz in backup._pastas():
        arquivo = raiz / pasta.name / "manifesto.json"
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        dados["criado"] = antigo
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
    motivos = []
    monkeypatch.setattr(backup, "fazer_backup", lambda motivo: motivos.append(motivo))
    backup.backup_diario()
    assert motivos == ["diario"]


def test_restaurar_banco_corrompido_preserva_quarentena(ambiente):
    base, banco, cofre, opcoes = ambiente
    pasta = Path(backup.fazer_backup("pedido"))
    banco.write_bytes(b"banco corrompido")
    assert backup.verificar_banco() != "ok"
    resultado = backup.restaurar(pasta.name, confirmado=True)
    quarentena = Path(resultado["seguranca"])
    assert quarentena.name.startswith(".quarentena-")
    assert (quarentena / "secretario.db").read_bytes() == b"banco corrompido"
    assert (quarentena / "aviso.txt").exists()
    assert (quarentena / "cofre" / "nota.md").exists()
    assert backup.verificar_banco() == "ok"


def test_restauracao_recusa_zip_com_travessia(ambiente):
    pasta = Path(backup.fazer_backup("pedido"))
    for raiz in backup._pastas():
        copia = raiz / pasta.name
        with ZipFile(copia / "cofre.zip", "a") as arquivo:
            arquivo.writestr("../fora.txt", "inválido")
        manifesto = copia / "manifesto.json"
        dados = json.loads(manifesto.read_text(encoding="utf-8"))
        dados["arquivos"]["cofre.zip"] = backup._resumo(copia / "cofre.zip")
        manifesto.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ValueError, match="Caminho inválido"):
        backup.restaurar(pasta.name, confirmado=True)
    assert all(item["motivo"] != "antes_restaurar" for item in backup.listar_backups())


def test_ultimo_integro_usa_pasta_extra(ambiente):
    pasta = Path(backup.fazer_backup("pedido"))
    (pasta / "motor.txt").write_text("adulterado", encoding="utf-8")
    ultimo = backup.ultimo_backup_integro()
    assert Path(ultimo["caminho"]).parent == Path(ambiente[3]["pasta_backup_extra"])


def test_primeiro_backup_diario(ambiente):
    pasta = Path(backup.backup_diario())
    assert pasta.name.endswith("_diario")


@pytest.mark.parametrize("nome", ["../fora", "..", ".", "a/b"])
def test_restaura_recusa_nome_invalido(ambiente, nome):
    with pytest.raises(ValueError, match="Nome"):
        backup.restaurar(nome, confirmado=True)
