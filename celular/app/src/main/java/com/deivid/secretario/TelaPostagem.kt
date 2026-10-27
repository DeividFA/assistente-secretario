package com.deivid.secretario

import android.graphics.ImageDecoder
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun TelaPostagem(modelo: ConversaModelo) {
    val item by modelo.postagem.collectAsStateWithLifecycle()
    val ocupado by modelo.enviando.collectAsStateWithLifecycle()
    val contexto = LocalContext.current
    val galeria = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contexto.contentResolver.takePersistableUriPermission(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
            modelo.postagem.value?.let { modelo.editarPostagem(it.copy(imagem = uri.toString())) }
        }
    }
    item?.let { rascunho ->
        val imagem = remember(rascunho.imagem) {
            if (rascunho.imagem.isBlank()) null else runCatching {
                ImageDecoder.decodeBitmap(ImageDecoder.createSource(contexto.contentResolver, Uri.parse(rascunho.imagem))) { decoder, info, _ ->
                    val escala = 600.0 / maxOf(info.size.width, info.size.height).coerceAtLeast(600)
                    decoder.setTargetSize((info.size.width * escala).toInt().coerceAtLeast(1), (info.size.height * escala).toInt().coerceAtLeast(1))
                }.asImageBitmap()
            }.getOrNull()
        }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(8.dp)) {
                Text("Rascunho · ${rascunho.rede}")
                OutlinedTextField(rascunho.texto, { modelo.editarPostagem(rascunho.copy(texto = it)) },
                    Modifier.fillMaxWidth().heightIn(max = 160.dp), enabled = !ocupado, label = { Text("Edite antes de aprovar") })
                imagem?.let { Image(it, "Imagem escolhida", Modifier.fillMaxWidth().height(100.dp)) }
                Row {
                    TextButton(onClick = { galeria.launch(arrayOf("image/*")) }, enabled = !ocupado) { Text("Galeria") }
                    TextButton(onClick = { modelo.editarPostagem(rascunho.copy(imagem = "")) }, enabled = !ocupado) { Text("Sem imagem") }
                }
                Button(onClick = { modelo.compartilharPostagem() }, enabled = !ocupado && rascunho.texto.isNotBlank()) {
                    Text("Aprovar e abrir no app")
                }
                Text("Escolha ${rascunho.rede}. A Acessibilidade prepara e pergunta: Posso publicar? Depois, volte aqui para confirmar o resultado.")
            }
        }
    }
}
