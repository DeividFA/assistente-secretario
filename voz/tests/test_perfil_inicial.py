from pathlib import Path

import memoria


def test_perfil_preserva_dados_e_ignora_vazios(tmp_path):
    perfil = tmp_path / 'Perfil' / 'Dados pessoais.md'
    perfil.parent.mkdir()
    original = '# Dados pessoais\n\n- **Nome:** Deivid\n- Cidade: Curitiba\n- Documento: preservar\n'
    perfil.write_text(original, encoding='utf-8')
    memoria.salvar_perfil_inicial({'nome': ' ', 'cidade': '', 'ocupacao': None}, tmp_path)
    assert perfil.read_text(encoding='utf-8') == original
    assert memoria.ler_perfil_inicial(tmp_path)['nome'] == 'Deivid'
    memoria.salvar_perfil_inicial({'nome': 'Dê'}, tmp_path)
    texto = perfil.read_text(encoding='utf-8')
    assert 'Nome: Dê' in texto
    assert 'Documento: preservar' in texto
    assert 'Cidade: Curitiba' in texto
    assert '**Nome:** Deivid' not in texto


def test_perfil_le_experiencia_e_campo_vazio(tmp_path):
    perfil = tmp_path / 'Perfil'
    perfil.mkdir()
    (perfil / 'Dados pessoais.md').write_text('# Perfil\n- Nome:\n- Cidade: Recife\n', encoding='utf-8')
    (perfil / 'Experiência.md').write_text('# Experiência\n- Cargo: Analista\n', encoding='utf-8')
    respostas = memoria.ler_perfil_inicial(tmp_path)
    assert respostas['nome'] == ''
    assert respostas['cidade'] == 'Recife'
    assert respostas['ocupacao'] == 'Analista'


def test_perfil_cria_notas_liga_interesses_sem_duplicar(tmp_path):
    respostas = {'nome': 'Deivid', 'ocupacao': 'Analista', 'cidade': 'Recife',
                 'rotina': 'De manhã', 'tarefas': 'Organizar agenda',
                 'estilo': 'Curtas e diretas; informal', 'nunca': 'Publicar',
                 'interesses': ['Tecnologia', '../inválido'], 'interesses_livres': 'Astronomia'}
    memoria.salvar_perfil_inicial(respostas, tmp_path)
    memoria.salvar_perfil_inicial(respostas, tmp_path)
    atual = memoria.ler_perfil_inicial(tmp_path)
    for chave, valor in respostas.items():
        if chave != 'interesses':
            assert atual[chave] == valor
    assert atual['interesses'] == ['Tecnologia']
    hub = (tmp_path / 'Assuntos' / 'Tecnologia.md').read_text(encoding='utf-8')
    assert hub.count('Interesse do Deivid') == 1
    assert '[[Perfil/Dados pessoais]]' in hub
    assert (tmp_path / '.secretario' / 'indice.json').exists()


def test_perfil_nao_grava_endereco(tmp_path):
    memoria.salvar_perfil_inicial({'cidade': 'Recife', 'endereco': 'segredo'}, tmp_path)
    memoria.salvar_perfil_inicial({'cidade': 'Rua das Flores, 123, Recife'}, tmp_path)
    assert memoria.ler_perfil_inicial(tmp_path)['cidade'] == 'Recife'
    texto = (tmp_path / 'Perfil' / 'Dados pessoais.md').read_text(encoding='utf-8')
    assert 'Flores' not in texto
    assert 'segredo' not in texto
