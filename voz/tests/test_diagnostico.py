"""Diagnóstico usando somente SQLite temporário e eventos falsos."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostico
import registro


def test_assinatura_ignora_linhas():
    def falhar(linha):
        try:
            if linha:
                raise ValueError('mesmo erro')
            raise ValueError('mesmo erro')
        except ValueError as erro:
            return diagnostico.assinatura(erro, erro.__traceback__)
    assert falhar(True) == falhar(False)


def test_contagem_estados_e_segredos(tmp_path):
    banco = tmp_path / 'bugs.db'
    for _ in range(4):
        id = diagnostico.registrar_bug('teste', ValueError('token=segredo'),
                                      contexto={'motor': 'codex', 'token': 'segredo'}, banco=banco)
    bug = registro.detalhe_bug(id, banco)
    assert bug['ocorrencias'] == 4
    assert 'segredo' not in bug['resumo'] + bug['contexto'] + bug['traceback']
    for estado in ('informado', 'aprovado', 'corrigindo', 'falhou', 'corrigido', 'ignorado'):
        registro.atualizar_bug(id, banco, estado=estado)
        assert registro.detalhe_bug(id, banco)['estado'] == estado


def test_sintomas_sem_recontar_janela(tmp_path):
    banco = tmp_path / 'bugs.db'
    eventos = ([{'autor': 'ERRO', 'texto': 'motor indisponível', 'motor': 'codex'}] * 3
               + [{'autor': 'Transcrição', 'texto': ''}] * 5
               + [{'autor': 'Ferramenta', 'texto': 'abrir:erro'}] * 3)
    assert len(diagnostico.detectar_sintomas(eventos, banco)) == 3
    diagnostico.detectar_sintomas(eventos, banco)
    assert len(registro.listar_bugs(banco)) == 3
    assert all(b['ocorrencias'] == 1 for b in registro.listar_bugs(banco))


def test_importar_queda(tmp_path):
    banco = tmp_path / 'bugs.db'
    arquivo = tmp_path / 'bug_1.json'
    arquivo.write_text('{"codigo": 1, "stderr": "falhou"}', encoding='utf-8')
    diagnostico.importar_quedas(tmp_path, banco)
    assert not arquivo.exists()
    assert registro.listar_bugs(banco)[0]['estado'] == 'novo'


def test_saude_completa_com_dependencias_falsas(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import backup
    import memoria
    monkeypatch.setattr(backup, 'verificar_banco', lambda: 'ok')
    monkeypatch.setattr(memoria, 'COFRE', tmp_path)
    monkeypatch.setattr(diagnostico.shutil, 'disk_usage',
                        lambda pasta: SimpleNamespace(free=3 * 1024 ** 3))
    class Resposta:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(diagnostico.urllib.request, 'urlopen', lambda *a, **k: Resposta())
    chamadas = []
    def rodar(args, **opcoes):
        chamadas.append((args, opcoes))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(diagnostico.subprocess, 'run', rodar)
    assert all(diagnostico.verificar_saude(completo=True, microfone=lambda: True).values())
    assert chamadas[0][0][1:] == ['-m', 'pytest', 'voz/tests', '-q']
    assert chamadas[0][1]['timeout'] == 300
