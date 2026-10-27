package com.deivid.secretario

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.FileProvider
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.Request

object VerificacaoApk {
    fun maisNova(instalada: Long, disponivel: Long): Boolean = disponivel > instalada

    fun conferir(entrada: InputStream, esperado: String): Boolean {
        if (!esperado.matches(Regex("[a-fA-F0-9]{64}"))) return false
        val resumo = MessageDigest.getInstance("SHA-256")
        val bloco = ByteArray(8192)
        while (true) {
            val tamanho = entrada.read(bloco)
            if (tamanho < 0) break
            resumo.update(bloco, 0, tamanho)
        }
        val obtido = resumo.digest().joinToString("") { "%02x".format(it) }
        return MessageDigest.isEqual(obtido.toByteArray(), esperado.lowercase().toByteArray())
    }
}

private data class VersaoApk(val codigo: Long, val nome: String, val sha256: String, val base: String, val pc: Pareamento)
private val clienteAtualizacao = OkHttpClient.Builder().connectTimeout(1500, TimeUnit.MILLISECONDS)
    .callTimeout(3, TimeUnit.MINUTES).followRedirects(false).followSslRedirects(false).build()

private fun requisicaoApk(base: String, caminho: String, pc: Pareamento) = Request.Builder()
    .url("$base$caminho").header("Authorization", "Bearer ${pc.token}").build()

@Composable
fun Atualizacao(configuracao: Configuracao) {
    val contexto = LocalContext.current
    val escopo = rememberCoroutineScope()
    val preferencias = remember { contexto.getSharedPreferences("atualizacao", Context.MODE_PRIVATE) }
    var versao by remember { mutableStateOf<VersaoApk?>(null) }
    var mensagem by remember { mutableStateOf("") }
    var ocupado by remember { mutableStateOf(false) }
    var pendente by remember { mutableStateOf<Pair<File, VersaoApk>?>(null) }

    fun abrirInstalador(arquivo: File, nova: VersaoApk) {
        escopo.launch {
            try {
                check(configuracao.pareamento() == nova.pc) { "O pareamento mudou; consulte novamente." }
                check(withContext(Dispatchers.IO) { arquivo.inputStream().use { VerificacaoApk.conferir(it, nova.sha256) } }) {
                    "SHA-256 diferente; APK descartado."
                }
                val uri = FileProvider.getUriForFile(contexto, "${contexto.packageName}.apk", arquivo)
                contexto.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
            } catch (erro: Exception) {
                if (erro is CancellationException) throw erro
                arquivo.delete(); mensagem = erro.message ?: "Não foi possível abrir o instalador."
            }
        }
    }
    val permissao = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        pendente?.let { (arquivo, nova) ->
            if (contexto.packageManager.canRequestPackageInstalls()) abrirInstalador(arquivo, nova)
            else mensagem = "Permita instalar apps desta fonte e tente novamente."
        }
        pendente = null
    }
    fun consultar(manual: Boolean) {
        if (ocupado) return
        val pc = configuracao.pareamento() ?: run { if (manual) mensagem = "Pareie o PC primeiro."; return }
        val agora = System.currentTimeMillis()
        val ultima = preferencias.getLong("ultima_consulta", 0)
        if (!manual && ultima != 0L && agora - ultima < TimeUnit.DAYS.toMillis(1)) return
        preferencias.edit().putLong("ultima_consulta", agora).commit()
        ocupado = true
        escopo.launch {
            try {
                versao = withContext(Dispatchers.IO) {
                    var falha: Exception? = null
                    for (host in pc.hosts) {
                        try {
                            val base = "http://$host:${pc.porta}"
                            clienteAtualizacao.newCall(requisicaoApk(base, "/apk/versao", pc)).execute().use { resposta ->
                                check(resposta.isSuccessful) { "Ponte: HTTP ${resposta.code}" }
                                val dados = Json.parseToJsonElement(resposta.body!!.string()).jsonObject
                                val nova = VersaoApk(dados.getValue("versionCode").jsonPrimitive.long,
                                    dados.getValue("versionName").jsonPrimitive.content,
                                    dados.getValue("sha256").jsonPrimitive.content, base, pc)
                                require(nova.codigo > 0 && nova.nome.isNotBlank() && nova.sha256.matches(Regex("[a-fA-F0-9]{64}")))
                                return@withContext nova.takeIf { VerificacaoApk.maisNova(BuildConfig.VERSION_CODE.toLong(), it.codigo) }
                            }
                        } catch (erro: Exception) { falha = erro }
                    }
                    throw falha ?: IllegalStateException("PC indisponível")
                }
                mensagem = versao?.let { "Há uma versão nova: ${it.nome}" } ?: "O app está atualizado."
            } catch (erro: Exception) {
                if (erro is CancellationException) throw erro
                versao = null; mensagem = "Atualização indisponível: ${erro.message}"
            } finally { ocupado = false }
        }
    }
    LaunchedEffect(Unit) { consultar(false) }
    TextButton(onClick = { consultar(true) }, enabled = !ocupado) { Text("Verificar atualização") }
    if (mensagem.isNotEmpty()) Text(mensagem)
    versao?.let { nova ->
        TextButton(enabled = !ocupado, onClick = {
            ocupado = true
            escopo.launch {
                val arquivo = File(contexto.cacheDir, "atualizacoes/secretario.apk")
                try {
                    check(configuracao.pareamento() == nova.pc) { "O pareamento mudou; consulte novamente." }
                    withContext(Dispatchers.IO) {
                        arquivo.parentFile!!.mkdirs()
                        arquivo.delete()
                        clienteAtualizacao.newCall(requisicaoApk(nova.base, "/apk", nova.pc)).execute().use { resposta ->
                            check(resposta.isSuccessful) { "Download: HTTP ${resposta.code}" }
                            resposta.body!!.byteStream().use { entrada -> arquivo.outputStream().use { entrada.copyTo(it) } }
                        }
                        check(arquivo.inputStream().use { VerificacaoApk.conferir(it, nova.sha256) }) { "SHA-256 diferente; consulte novamente." }
                    }
                    if (contexto.packageManager.canRequestPackageInstalls()) abrirInstalador(arquivo, nova)
                    else {
                        pendente = arquivo to nova
                        permissao.launch(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${contexto.packageName}")))
                    }
                } catch (erro: Exception) {
                    arquivo.delete()
                    if (erro is CancellationException) throw erro
                    mensagem = erro.message ?: "Falha no download."
                } finally { ocupado = false }
            }
        }) { Text("Baixar e instalar ${nova.nome}") }
    }
}
