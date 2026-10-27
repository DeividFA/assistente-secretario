import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import segundo_plano as plano


@pytest.mark.parametrize("liberar", [True, False])
def test_esperar_vez_com_relogio_falso(monkeypatch, liberar):
    agora = [0.0]
    monkeypatch.setattr(plano.time, "monotonic", lambda: agora[0])
    monkeypatch.setattr(plano.time, "sleep", lambda segundos: agora.__setitem__(0, agora[0] + segundos))
    monkeypatch.setattr(plano, "ocioso_ha", lambda: agora[0] if liberar else 0)
    assert plano.esperar_vez(min_ocioso=0.2, max_espera=0.4) is liberar
    assert agora[0] <= 0.4


@pytest.mark.parametrize("falhar", [False, True])
def test_restaura_estado_mesmo_com_erro(monkeypatch, falhar):
    dados = {13: "texto copiado", 49152: b"formato rico"}
    estado = {"janela": 10, "cursor": (5, 6)}
    clipboard = SimpleNamespace(
        OpenClipboard=lambda: None, CloseClipboard=lambda: None,
        EnumClipboardFormats=lambda anterior: {0: 13, 13: 49152, 49152: 0}[anterior],
        GetClipboardData=dados.__getitem__, EmptyClipboard=dados.clear,
        SetClipboardData=lambda formato, valor: dados.__setitem__(formato, valor),
    )
    gui = SimpleNamespace(
        GetForegroundWindow=lambda: estado["janela"], GetCursorPos=lambda: estado["cursor"],
        IsWindow=lambda janela: True,
        SetForegroundWindow=lambda janela: estado.__setitem__("janela", janela),
        SetCursorPos=lambda cursor: estado.__setitem__("cursor", cursor),
    )
    monkeypatch.setattr(plano, "_win32", lambda: (gui, clipboard, gui))

    def agir():
        with plano.restaurando_estado():
            estado.update(janela=20, cursor=(30, 40))
            dados.clear()
            dados[13] = "colado"
            if falhar:
                raise ValueError("erro simulado")

    if falhar:
        with pytest.raises(ValueError, match="erro simulado"):
            agir()
    else:
        agir()
    assert estado == {"janela": 10, "cursor": (5, 6)}
    assert dados == {13: "texto copiado", 49152: b"formato rico"}


def test_clipboard_nao_restauravel_recusa_antes_da_acao(monkeypatch):
    fechou = []
    gui = SimpleNamespace(GetForegroundWindow=lambda: 1, GetCursorPos=lambda: (0, 0))
    clipboard = SimpleNamespace(OpenClipboard=lambda: None,
                                CloseClipboard=lambda: fechou.append(True),
                                EnumClipboardFormats=lambda anterior: 2)
    monkeypatch.setattr(plano, "_win32", lambda: (gui, clipboard, gui))
    with pytest.raises(RuntimeError, match="não restaurável"):
        with plano.restaurando_estado():
            pytest.fail("Não deve agir.")
    assert fechou == [True]


@pytest.fixture
def arvore():
    return [SimpleNamespace(element_info=SimpleNamespace(name="Nome", automation_id="nome")),
            SimpleNamespace(element_info=SimpleNamespace(name="Salvar", automation_id="salvar"))]


@pytest.mark.parametrize("alvo", [0, "0", "Nome", "nome"])
def test_resolver_alvo(arvore, alvo):
    assert plano._resolver_alvo(arvore, alvo) is arvore[0]


@pytest.mark.parametrize("alvo", [-1, "8", "Ausente"])
def test_resolver_alvo_invalido(arvore, alvo):
    with pytest.raises(ValueError):
        plano._resolver_alvo(arvore, alvo)


def test_resolver_alvo_ambiguo(arvore):
    arvore[1].element_info.name = "Nome"
    with pytest.raises(ValueError, match="ambíguo"):
        plano._resolver_alvo(arvore, "Nome")


@pytest.fixture
def sentidos_falsos():
    # Carrega só as funções físicas reais, sem importar dispositivos ou o servidor.
    nomes = {"clicar", "arrastar", "digitar", "teclas", "rolar", "focar_janela"}
    caminho = Path(plano.__file__).with_name("sentidos_mcp.py")
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    funcoes = [no for no in arvore.body if isinstance(no, ast.FunctionDef) and no.name in nomes]
    contexto = {"segundo_plano": plano, "mcp": SimpleNamespace(tool=lambda: lambda f: f)}
    exec(compile(ast.Module(body=funcoes, type_ignores=[]), str(caminho), "exec"), contexto)
    return contexto


@pytest.mark.parametrize("nome,args", [
    ("clicar", (1, 2)), ("arrastar", (1, 2, 3, 4)), ("digitar", ("oi",)),
    ("teclas", ("ctrl+c",)), ("rolar", (1,)), ("focar_janela", ("Editor",)),
])
def test_fisicas_recusam_sem_tocar_dispositivos(monkeypatch, sentidos_falsos, nome, args):
    monkeypatch.setattr(plano, "esperar_vez", lambda: False)
    assert sentidos_falsos[nome](*args) == plano.OCUPADO


def test_gemma_reaproveita_protecao(monkeypatch, sentidos_falsos):
    import acoes
    monkeypatch.setattr(plano, "esperar_vez", lambda: False)
    monkeypatch.setattr(acoes, "_sentidos", lambda nome, *args, **kw: sentidos_falsos[nome](*args, **kw))
    for nome, args in [("clicar", {"x": 1, "y": 2}), ("digitar", {"texto": "oi"}),
                       ("teclas", {"combinacao": "enter"}), ("rolar", {"quantidade": 1}),
                       ("focar_janela", {"titulo": "Editor"})]:
        assert acoes.executar(nome, args) == {"ok": False, "texto": plano.OCUPADO, "imagem": None}


@pytest.fixture
def uia_falsa(monkeypatch, arvore):
    class SemPadrao(Exception):
        pass

    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines",
                        SimpleNamespace(NoPatternInterfaceError=SemPadrao))
    janela = SimpleNamespace(descendants=lambda: arvore)
    monkeypatch.setattr(plano, "_janela", lambda titulo: janela)
    return SemPadrao


def test_preencher_usa_value_pattern(monkeypatch, arvore, uia_falsa):
    valores = []
    arvore[0].iface_value = SimpleNamespace(SetValue=valores.append)
    assert plano.preencher_campo("Editor", "nome", "Deivid") == "Campo preenchido."
    assert valores == ["Deivid"]


@pytest.mark.parametrize("interface,metodo", [
    ("iface_invoke", "Invoke"), ("iface_toggle", "Toggle"), ("iface_selection_item", "Select"),
])
def test_acionar_usa_so_padroes(monkeypatch, uia_falsa, interface, metodo):
    chamadas = []

    class Elemento:
        def __getattr__(self, nome):
            if nome == interface:
                return SimpleNamespace(**{metodo: lambda: chamadas.append(metodo)})
            raise uia_falsa()

    monkeypatch.setattr(plano, "_elementos", lambda janela: [Elemento()])
    assert plano.acionar("Editor", "0") == "Elemento acionado."
    assert chamadas == [metodo]


def test_ler_janela_com_valores_e_limite(arvore, uia_falsa):
    for elemento in arvore:
        elemento.element_info.control_type = "Edit"
        elemento.element_info.element = SimpleNamespace(CurrentIsPassword=False)
        elemento.iface_value = SimpleNamespace(CurrentValue="conteúdo")
    texto = plano.ler_janela("Editor")
    assert '"indice": 0' in texto
    assert '"automation_id": "nome"' in texto
    assert '"valor": "conteúdo"' in texto
    assert len(plano.ler_janela("Editor", limite=20)) == 20


def test_sem_uia_nao_tenta_ferramentas_fisicas(monkeypatch, uia_falsa):
    monkeypatch.setattr(plano, "_janela", lambda titulo: SimpleNamespace(descendants=lambda: []))
    with pytest.raises(RuntimeError, match="não expõe"):
        plano.ler_janela("Editor")


@pytest.mark.parametrize("ele_mexeu", [False, True])
def test_sequencia_mantem_foco_e_devolve_depois(monkeypatch, ele_mexeu):
    estado = {"janela": 10, "cursor": (0, 0), "entrada": 0, "ticks": 1000}
    clipboard = SimpleNamespace(OpenClipboard=lambda: None, CloseClipboard=lambda: None,
                                EnumClipboardFormats=lambda anterior: 0, EmptyClipboard=lambda: None)
    gui = SimpleNamespace(
        GetForegroundWindow=lambda: estado["janela"], GetCursorPos=lambda: estado["cursor"],
        IsWindow=lambda janela: True, SetCursorPos=lambda cursor: None,
        SetForegroundWindow=lambda janela: estado.__setitem__("janela", janela))
    monkeypatch.setattr(plano, "_win32", lambda: (gui, clipboard, gui))
    monkeypatch.setattr(plano, "_ticks", lambda: estado["ticks"])
    monkeypatch.setattr(plano, "_ultima_entrada", lambda: estado["entrada"])
    monkeypatch.setattr(plano, "esperar_vez", lambda: True)
    monkeypatch.setattr(plano, "SEQUENCIA", 0.2)

    @plano.fisica
    def focar():
        estado.update(janela=20, entrada=1000)

    @plano.fisica
    def digitar():
        estado["entrada"] = 1100
        return "digitado"

    focar()
    assert estado["janela"] == 20  # o digitar seguinte vai para a janela focada
    estado["ticks"] = 1100
    assert digitar() == "digitado" and estado["janela"] == 20
    if ele_mexeu:
        estado["entrada"] = 5000  # depois da nossa última ação
    import time
    time.sleep(0.5)
    assert estado["janela"] == (20 if ele_mexeu else 10)


def test_entrada_injetada_nao_conta_como_uso(monkeypatch):
    monkeypatch.setattr(plano, "_nossa_ate", 2000)
    monkeypatch.setattr(plano, "_ultima_entrada", lambda: 1900)
    assert plano.entrada_foi_nossa()
    monkeypatch.setattr(plano, "_ultima_entrada", lambda: 2100)
    assert not plano.entrada_foi_nossa()
