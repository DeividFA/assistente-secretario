"""Reparo aprovado, isolado em branch e validado antes do merge."""

from pathlib import Path
import subprocess
import sys
import threading

import backup
import motores_cli
import registro

REPO = Path(__file__).resolve().parents[1]
_trava = threading.Lock()


def _rodar(args, repo):
    return subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=300,
                          creationflags=0x08000000 if sys.platform == 'win32' else 0).stdout.strip()


def verificar(repo):
    _rodar([sys.executable, '-m', 'pytest', 'voz/tests', '-q'], repo)
    for arquivo in (Path(repo) / 'app').rglob('*.js'):
        if 'node_modules' not in arquivo.parts and 'dist' not in arquivo.parts:
            _rodar(['node', '--check', str(arquivo)], repo)


def executar(id, diretriz='', aprovado=False, repo=REPO, banco=registro.BANCO,
             executor=None, testar=None, fazer_backup=None):
    if not aprovado:
        return {'ok': False, 'texto': 'Preciso da aprovação explícita para este problema.'}
    if not _trava.acquire(blocking=False):
        return {'ok': False, 'texto': 'Já existe um reparo em andamento.'}
    repo = Path(repo)
    branch, criado, integrado = f'reparo/{int(id)}', False, False
    commit = None
    try:
        bug = registro.detalhe_bug(id, banco)
        if not bug or bug['tentativas'] >= 2 or bug['estado'] in ('corrigido', 'ignorado', 'corrigindo'):
            raise ValueError('Problema indisponível ou limite de duas tentativas atingido.')
        if _rodar(['git', 'status', '--porcelain', '--untracked-files=all'], repo):
            raise ValueError('O repositório tem alterações não commitadas.')
        principal = _rodar(['git', 'branch', '--show-current'], repo)
        if not principal or principal.startswith('reparo/'):
            raise ValueError('O repositório precisa estar no branch principal.')
        if _rodar(['git', 'branch', '--list', branch], repo):
            raise ValueError('O branch deste reparo já existe.')
        base = _rodar(['git', 'rev-parse', 'HEAD'], repo)
        registro.atualizar_bug(id, banco, estado='aprovado', diretriz=diretriz)
        (fazer_backup or backup.fazer_backup)('antes_reparo')
        _rodar(['git', 'switch', '-c', branch], repo)
        criado = True
        registro.atualizar_bug(id, banco, estado='corrigindo', tentativas=bug['tentativas'] + 1)
        pedido = (f"Problema {id}: {bug['resumo']}\nTraceback: {bug['traceback']}\n"
                  f"Contexto: {bug['contexto']}\nDiretriz do Deivid: {diretriz}\n"
                  'Corrija somente este problema e acrescente um teste que o reproduza. '
                  'Não altere dados do usuário: secretario.db, config.json, correcoes.json, '
                  'lembretes.json, motor.txt, cofre, backups ou chaves. '
                  'Não faça commit, não troque branches, não altere o git e nunca faça push.')
        (executor or motores_cli.executar)('codex', pedido, lambda evento: None, pasta=repo)
        if _rodar(['git', 'branch', '--show-current'], repo) != branch:
            raise RuntimeError('O executor mudou o branch.')
        if _rodar(['git', 'rev-parse', 'HEAD'], repo) != base:
            raise RuntimeError('O executor alterou o histórico git.')
        alterados = _rodar(['git', 'ls-files', '--modified', '--others', '--exclude-standard'], repo).splitlines()
        for caminho in alterados:
            partes = Path(caminho).parts
            if (Path(caminho).name.lower().startswith(('secretario.db', 'config.json', 'correcoes.json',
                                                     'lembretes.json', 'motor.txt'))
                    or any(p.lower() in ('cofre', 'backups', '.aws', '.secretario') for p in partes)
                    or Path(caminho).suffix.lower() in ('.key', '.pem')):
                raise RuntimeError('O reparo tentou alterar dados protegidos.')
        if not any(c.startswith('voz/tests/test_') for c in alterados):
            raise RuntimeError('O reparo não acrescentou o teste de reprodução.')
        (testar or verificar)(repo)
        _rodar(['git', 'add', '--all'], repo)
        _rodar(['git', 'commit', '-m', f'Corrige problema {id}'], repo)
        commit = _rodar(['git', 'rev-parse', 'HEAD'], repo)
        _rodar(['git', 'switch', principal], repo)
        _rodar(['git', 'merge', '--ff-only', branch], repo)
        integrado = True
        registro.atualizar_bug(id, banco, estado='corrigido', commit=commit)
        return {'ok': True, 'commit': commit, 'id': id,
                'texto': f"Corrigi {bug['resumo']}. Posso me reiniciar para aplicar?"}
    except Exception as erro:
        if criado and not integrado:
            # O estado inicial era limpo. Só desfaz o trabalho desta tentativa.
            try:
                _rodar(['git', 'switch', '--discard-changes', branch], repo)
                _rodar(['git', 'reset', '--hard', base], repo)
                _rodar(['git', 'clean', '-fd'], repo)
                _rodar(['git', 'switch', principal], repo)
                _rodar(['git', 'branch', '-D', branch], repo)
            except Exception as falha:
                erro = RuntimeError(f'{erro}; limpeza do branch falhou: {falha}')
            registro.atualizar_bug(id, banco, estado='falhou')
        return {'ok': False, 'texto': 'Não consegui reparar: ' + str(erro).splitlines()[0][:240]}
    finally:
        _trava.release()
