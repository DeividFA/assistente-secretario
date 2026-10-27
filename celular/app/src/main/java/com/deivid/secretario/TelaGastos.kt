package com.deivid.secretario

import android.Manifest
import android.content.Intent
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun TelaGastos(modelo: ConversaModelo, modifier: Modifier = Modifier) {
    val contexto = LocalContext.current
    val escopo = rememberCoroutineScope()
    val itens by modelo.listaGastos.collectAsStateWithLifecycle()
    val resumo by modelo.resumoGastos.collectAsStateWithLifecycle()
    val rascunho by modelo.rascunhoGasto.collectAsStateWithLifecycle()
    var camera by remember { mutableStateOf(false) }
    var csv by remember { mutableStateOf<String?>(null) }
    var colunaData by remember { mutableStateOf("data") }
    var colunaValor by remember { mutableStateOf("valor") }
    var colunaLocal by remember { mutableStateOf("estabelecimento") }
    var colunaCategoria by remember { mutableStateOf("categoria") }
    var colunaForma by remember { mutableStateOf("") }
    var categoria by remember { mutableStateOf("Mercado") }
    var limite by remember { mutableStateOf("") }
    var notificacoes by remember { mutableStateOf(modelo.preferenciasGastos.notificacoes) }
    var apps by remember { mutableStateOf(modelo.preferenciasGastos.apps()) }
    val financeiros = remember {
        contexto.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .filter { BloqueioFinanceiro().bloqueado(it.activityInfo.packageName, it.loadLabel(contexto.packageManager).toString()) }
            .distinctBy { it.activityInfo.packageName }.sortedBy { it.loadLabel(contexto.packageManager).toString() }
    }
    val permissao = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        camera = it
        if (!it) modelo.aviso.value = "Permita a câmera para ler o comprovante"
    }
    val arquivo = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) escopo.launch {
            try {
                csv = withContext(Dispatchers.IO) {
                    contexto.contentResolver.openInputStream(uri)!!.bufferedReader().use {
                        val texto = it.readText(); require(texto.length <= 1_000_000) { "CSV muito grande" }; texto
                    }
                }
            } catch (e: Exception) { modelo.aviso.value = "Não foi possível ler o CSV: ${e.message}" }
        }
    }
    LaunchedEffect(itens) { modelo.atualizarResumo() }
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(resumo)
        Text("Diga ou digite na conversa: gastei 45 reais no mercado ontem. Revise antes de confirmar.")
        Button(onClick = { permissao.launch(Manifest.permission.CAMERA) }) { Text("Ler foto de comprovante") }
        Text("OCR no aparelho. Ao capturar, o texto será enviado à sua IA para extração; a foto e o texto não são guardados.")
        if (camera) {
            LeitorComprovante(Modifier.fillMaxWidth().height(280.dp), receber = {
                camera = false; modelo.prepararGasto(it, foto = true)
            }, erro = { modelo.aviso.value = it })
            TextButton(onClick = { camera = false }) { Text("Fechar câmera") }
        }
        Button(onClick = { arquivo.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel")) }) { Text("Importar CSV") }
        csv?.let { texto ->
            Text("Cabeçalho: ${texto.lineSequence().firstOrNull().orEmpty().take(250)}")
            OutlinedTextField(colunaData, { colunaData = it }, label = { Text("Coluna de data") })
            OutlinedTextField(colunaValor, { colunaValor = it }, label = { Text("Coluna de valor (reais)") })
            OutlinedTextField(colunaLocal, { colunaLocal = it }, label = { Text("Coluna de estabelecimento (opcional)") })
            OutlinedTextField(colunaCategoria, { colunaCategoria = it }, label = { Text("Coluna de categoria (opcional)") })
            OutlinedTextField(colunaForma, { colunaForma = it }, label = { Text("Coluna de forma (opcional)") })
            Button(onClick = {
                modelo.importarCsv(texto, mapOf("data" to colunaData, "valor" to colunaValor,
                    "estabelecimento" to colunaLocal, "categoria" to colunaCategoria, "forma" to colunaForma).filterValues { it.isNotBlank() })
                csv = null
            }) { Text("Revisar importação") }
            TextButton(onClick = { csv = null }) { Text("Cancelar CSV") }
        }
        OutlinedTextField(categoria, { categoria = it }, label = { Text("Categoria do orçamento") })
        OutlinedTextField(limite, { limite = it }, label = { Text("Orçamento mensal em reais") })
        Button(onClick = { modelo.definirOrcamento(categoria, limite) }) { Text("Salvar orçamento") }
        Row { Switch(notificacoes, {
            notificacoes = it; modelo.preferenciasGastos.notificacoes = it
        }); Text("Ler notificações dos apps marcados") }
        Text("Só compras aprovadas e Pix enviado. Nenhum app é aberto. Os gastos aguardam sua confirmação.")
        if (notificacoes) {
            Button(onClick = { contexto.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }) { Text("Permitir acesso no Android") }
            financeiros.forEach { app ->
                val pacote = app.activityInfo.packageName
                Row { Checkbox(pacote in apps, {
                    modelo.preferenciasGastos.marcar(pacote, it); apps = modelo.preferenciasGastos.apps()
                }); Text(app.loadLabel(contexto.packageManager).toString()) }
            }
        }
        itens.forEach { item ->
            var novaCategoria by remember(item.id, item.categoria) { mutableStateOf(item.categoria) }
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) {
                Text("${item.data} · ${ParseGastos.reais(item.valor_centavos)} · ${item.estabelecimento}")
                Text("${item.origem} · ${if (item.confirmado) "confirmado" else "aguardando confirmação"}")
                OutlinedTextField(novaCategoria, { novaCategoria = it }, label = { Text("Categoria") })
                TextButton(onClick = { modelo.corrigirGasto(item, novaCategoria) }) { Text("Confirmar / corrigir categoria") }
            } }
        }
    }
    rascunho?.let { item ->
        var data by remember(item) { mutableStateOf(item.data) }
        var valor by remember(item) { mutableStateOf(ParseGastos.reais(item.valor).removePrefix("R$ ")) }
        var local by remember(item) { mutableStateOf(item.estabelecimento) }
        var cat by remember(item) { mutableStateOf(item.categoria) }
        var forma by remember(item) { mutableStateOf(item.forma) }
        AlertDialog(onDismissRequest = { modelo.rascunhoGasto.value = null }, title = { Text("Confirmar gasto") },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(data, { data = it }, label = { Text("Data AAAA-MM-DD") })
                OutlinedTextField(valor, { valor = it }, label = { Text("Valor em reais") })
                OutlinedTextField(local, { local = it }, label = { Text("Estabelecimento") })
                OutlinedTextField(cat, { cat = it }, label = { Text("Categoria") })
                OutlinedTextField(forma, { forma = it }, label = { Text("Forma (sem dados do cartão)") })
            } }, confirmButton = { TextButton(onClick = {
                runCatching {
                    java.time.LocalDate.parse(data)
                    item.copy(data = data, valor = ParseGastos.centavos(valor), estabelecimento = ParseGastos.seguro(local),
                        categoria = ParseGastos.seguro(cat).ifBlank { "Outros" }, forma = ParseGastos.seguro(forma))
                }.onSuccess { modelo.confirmarGasto(it) }.onFailure { modelo.aviso.value = "Revise a data e o valor" }
            }) { Text("Confirmar") } }, dismissButton = { TextButton(onClick = { modelo.rascunhoGasto.value = null }) { Text("Cancelar") } })
    }
}
