package com.deivid.secretario

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle

class MainActivity : ComponentActivity() {
    private lateinit var modelo: ConversaModelo
    private lateinit var voz: Voz
    private val pedidoVoz = mutableStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        modelo = ViewModelProvider(this)[ConversaModelo::class.java]
        voz = Voz(this, modelo::enviar) { modelo.aviso.value = it }
        if (savedInstanceState == null && intent.getBooleanExtra("ouvir", false)) pedidoVoz.value++
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Color(0xFF8EE3C4), onPrimary = Color(0xFF00382A),
                background = Color(0xFF171A20), surface = Color(0xFF242831)
            )) {
                val permissaoMicrofone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
                    if (ok) voz.ouvir() else modelo.aviso.value = "Permita o microfone para falar; você também pode digitar."
                }
                fun ouvir() {
                    if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
                        voz.ouvir()
                    else permissaoMicrofone.launch(Manifest.permission.RECORD_AUDIO)
                }
                LaunchedEffect(pedidoVoz.value) { if (pedidoVoz.value > 0) ouvir() }
                LaunchedEffect(Unit) { modelo.falar.collect { voz.dizer(it) } }
                val pedidoAcao by modelo.interfaceAcoes.pedido.collectAsStateWithLifecycle()
                var permissaoEmCurso by remember { mutableStateOf<PedidoAcao.Permissao?>(null) }
                val permissaoAcao = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { resultado ->
                    permissaoEmCurso?.let { pedido -> pedido.resposta.complete(pedido.nomes.all { resultado[it] == true }) }
                    permissaoEmCurso = null
                }
                LaunchedEffect(pedidoAcao) {
                    when (val pedido = pedidoAcao) {
                        is PedidoAcao.Permissao -> if (permissaoEmCurso !== pedido) {
                            permissaoEmCurso = pedido
                            permissaoAcao.launch(pedido.nomes.toTypedArray())
                        }
                        is PedidoAcao.Abrir -> if (!pedido.resposta.isCompleted) {
                            try { startActivity(pedido.intent); pedido.resposta.complete(Unit) }
                            catch (erro: Exception) { pedido.resposta.completeExceptionally(erro) }
                        }
                        else -> Unit
                    }
                }
                (pedidoAcao as? PedidoAcao.Confirmacao)?.let { pedido ->
                    AlertDialog(onDismissRequest = { pedido.resposta.complete(false) },
                        title = { Text("Confirmar ação") }, text = { Text(pedido.texto) },
                        confirmButton = { TextButton(onClick = { pedido.resposta.complete(true) }) { Text("Confirmar") } },
                        dismissButton = { TextButton(onClick = { pedido.resposta.complete(false) }) { Text("Cancelar") } })
                }
                Tela(modelo, ::ouvir)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra("ouvir", false)) pedidoVoz.value++
    }
    override fun onStart() { super.onStart(); modelo.iniciar() }
    override fun onStop() { voz.silenciar(); modelo.parar(); super.onStop() }
    override fun onDestroy() { voz.fechar(); super.onDestroy() }
}

@Composable
private fun Tela(modelo: ConversaModelo, ouvir: () -> Unit) {
    var configuracoes by remember { mutableStateOf(false) }
    var gastos by remember { mutableStateOf(false) }
    var texto by remember { mutableStateOf("") }
    var fato by remember { mutableStateOf("") }
    val mensagens by modelo.mensagens.collectAsStateWithLifecycle()
    val fila by modelo.fila.collectAsStateWithLifecycle()
    val estado by modelo.estado.collectAsStateWithLifecycle()
    val cerebro by modelo.cerebro.collectAsStateWithLifecycle()
    val conectado by modelo.conectado.collectAsStateWithLifecycle()
    val enviando by modelo.enviando.collectAsStateWithLifecycle()
    val aviso by modelo.aviso.collectAsStateWithLifecycle()
    val fatos by modelo.fatos.collectAsStateWithLifecycle()
    val rolagem = rememberLazyListState()
    LaunchedEffect(mensagens.size) { if (mensagens.isNotEmpty()) rolagem.animateScrollToItem(mensagens.lastIndex) }
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).safeDrawingPadding().imePadding().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Secretário · $cerebro", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary)
            TextButton(onClick = { configuracoes = !configuracoes; gastos = false }) { Text(if (configuracoes) "Conversa" else "Config.") }
        }
        Text("PC ${if (conectado) "conectado" else "desconectado"} · $estado", color = MaterialTheme.colorScheme.onSurface)
        TextButton(onClick = { gastos = !gastos; configuracoes = false }) { Text(if (gastos) "Voltar à conversa" else "Gastos") }
        aviso?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
        if (gastos) {
            TelaGastos(modelo, Modifier.weight(1f))
        } else if (configuracoes) {
            Configuracoes(modelo, fatos, Modifier.weight(1f))
        } else {
            TelaPostagem(modelo)
            LazyColumn(state = rolagem, modifier = Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(mensagens, key = { it.id }) { mensagem ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("${mensagem.autor} · ${mensagem.origem}", color = MaterialTheme.colorScheme.primary)
                            Text(mensagem.texto)
                        }
                    }
                }
            }
            Text("Fila do PC (${fila.size})", color = MaterialTheme.colorScheme.primary)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 110.dp)) {
                items(fila, key = { it.id }) { Text("#${it.id} · ${it.status} · ${it.comando}", color = MaterialTheme.colorScheme.onSurface) }
            }
            OutlinedTextField(texto, { texto = it }, Modifier.fillMaxWidth(), label = { Text("Mensagem") }, maxLines = 4)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = ouvir, enabled = !enviando) { Text("Microfone") }
                Button(onClick = { modelo.enviar(texto); texto = "" }, enabled = !enviando && texto.isNotBlank()) {
                    Text(if (enviando) "Enviando…" else "Enviar")
                }
            }
            Row(Modifier.fillMaxWidth()) {
                OutlinedTextField(fato, { fato = it }, Modifier.weight(1f), label = { Text("Fato para lembrar no PC") })
                TextButton(onClick = { modelo.aprender(fato); fato = "" }, enabled = fato.isNotBlank()) { Text("Guardar") }
            }
        }
    }
    if (!gastos && modelo.rascunhoGasto.collectAsStateWithLifecycle().value != null) {
        LaunchedEffect(Unit) { gastos = true; configuracoes = false }
    }
}

@Composable
private fun Configuracoes(modelo: ConversaModelo, fatos: Int, modifier: Modifier) {
    val inicial = remember { modelo.configuracao.nuvem() }
    var provedor by remember { mutableStateOf(inicial.provedor) }
    var base by remember { mutableStateOf(inicial.base) }
    var nomeModelo by remember { mutableStateOf(inicial.modelo) }
    var chave by remember { mutableStateOf(inicial.chave) }
    var leitor by remember { mutableStateOf(false) }
    val contexto = androidx.compose.ui.platform.LocalContext.current
    var pacoteBloqueado by remember { mutableStateOf("") }
    var pareado by remember { mutableStateOf(modelo.configuracao.pareamento() != null) }
    val permissaoCamera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        leitor = ok
        if (!ok) modelo.aviso.value = "Permita a câmera para ler o QR do PC."
    }
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("PC ${if (pareado) "pareado" else "não pareado"}", color = MaterialTheme.colorScheme.primary)
        Text("Abra Conectar celular no PC e leia o QR. Fora de casa, ative Tailscale nos dois aparelhos.", color = MaterialTheme.colorScheme.onSurface)
        Button(onClick = { permissaoCamera.launch(Manifest.permission.CAMERA) }) { Text("Ler QR do PC") }
        if (leitor) {
            LeitorQr(Modifier.fillMaxWidth().height(280.dp), receber = {
                modelo.parear(it); leitor = false; pareado = modelo.configuracao.pareamento() != null
            }, erro = { modelo.aviso.value = it })
            TextButton(onClick = { leitor = false }) { Text("Fechar câmera") }
        }
        if (pareado) TextButton(onClick = { modelo.esquecerPc(); pareado = false }) { Text("Esquecer PC") }
        Text("Fatos aguardando sincronização: $fatos", color = MaterialTheme.colorScheme.onSurface)
        Text("Acessibilidade: nunca bancos, senhas ou telas seguras. Operação exige Android 14+.")
        Button(onClick = { contexto.startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)) }) {
            Text("Ativar Acessibilidade")
        }
        OutlinedTextField(pacoteBloqueado, { pacoteBloqueado = it }, label = { Text("Pacote para bloquear (só acrescentar)") })
        Button(onClick = {
            runCatching { ListaBloqueioUsuario(contexto).acrescentar(pacoteBloqueado) }
                .onSuccess { pacoteBloqueado = ""; modelo.aviso.value = "App acrescentado ao bloqueio" }
                .onFailure { modelo.aviso.value = "Pacote inválido" }
        }) { Text("Acrescentar bloqueio") }
        Text("IA na nuvem", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
        Provedor.entries.forEach { p ->
            Row {
                RadioButton(selected = provedor == p, onClick = { provedor = p; base = p.base; nomeModelo = p.modelo; chave = "" })
                TextButton(onClick = { provedor = p; base = p.base; nomeModelo = p.modelo; chave = "" }) { Text(p.titulo) }
            }
        }
        OutlinedTextField(base, { base = it }, label = { Text("URL base compatível com OpenAI (HTTPS)") }, singleLine = true)
        OutlinedTextField(nomeModelo, { nomeModelo = it }, label = { Text("Modelo") }, singleLine = true)
        OutlinedTextField(chave, { chave = it }, label = { Text("Chave da API") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        Button(onClick = {
            runCatching { modelo.configuracao.salvar(ConfigNuvem(provedor, base.trim(), nomeModelo.trim(), chave.trim())) }
                .onSuccess { modelo.aviso.value = "Configuração salva no cofre do Android" }
                .onFailure { modelo.aviso.value = it.message }
        }) { Text("Salvar") }
        Text("A C2 não possui ações de apps. Use Guardar para colocar fatos na fila local. A sincronização ocorre enquanto o app está aberto.", color = MaterialTheme.colorScheme.onSurface)
    }
}
