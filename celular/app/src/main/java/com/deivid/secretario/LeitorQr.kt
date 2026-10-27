package com.deivid.secretario

import android.annotation.SuppressLint
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@SuppressLint("UnsafeOptInUsageError")
@Composable
fun LeitorQr(modifier: Modifier = Modifier, receber: (String) -> Unit, erro: (String) -> Unit) {
    val contexto = LocalContext.current
    val ciclo = LocalLifecycleOwner.current
    val receberAtual by rememberUpdatedState(receber)
    val erroAtual by rememberUpdatedState(erro)
    val visualizacao = remember { PreviewView(contexto) }
    DisposableEffect(ciclo) {
        val executor = Executors.newSingleThreadExecutor()
        val principal = ContextCompat.getMainExecutor(contexto)
        val scanner = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
        val futuro = ProcessCameraProvider.getInstance(contexto)
        val ocupado = AtomicBoolean(false)
        val entregue = AtomicBoolean(false)
        var encerrado = false
        var provedor: ProcessCameraProvider? = null
        var previa: Preview? = null
        var analise: ImageAnalysis? = null
        futuro.addListener({
            if (!encerrado) try {
                val camera = futuro.get()
                provedor = camera
                previa = Preview.Builder().build().also { it.setSurfaceProvider(visualizacao.surfaceProvider) }
                analise = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build().also { a ->
                    a.setAnalyzer(executor) { quadro ->
                        val imagem = quadro.image
                        if (imagem == null || entregue.get() || !ocupado.compareAndSet(false, true)) quadro.close()
                        else scanner.process(InputImage.fromMediaImage(imagem, quadro.imageInfo.rotationDegrees))
                            .addOnSuccessListener(principal) { codigos ->
                                val texto = codigos.firstOrNull { it.rawValue != null }?.rawValue
                                if (!encerrado && texto != null && entregue.compareAndSet(false, true)) receberAtual(texto)
                            }
                            .addOnFailureListener(principal) { if (!encerrado) erroAtual("Não foi possível ler o QR") }
                            .addOnCompleteListener { ocupado.set(false); quadro.close() }
                    }
                }
                camera.bindToLifecycle(ciclo, CameraSelector.DEFAULT_BACK_CAMERA, previa!!, analise!!)
            } catch (_: Exception) { erroAtual("Câmera indisponível. Verifique a permissão.") }
        }, principal)
        onDispose {
            encerrado = true
            analise?.clearAnalyzer()
            previa?.let { provedor?.unbind(it) }
            analise?.let { provedor?.unbind(it) }
            scanner.close()
            executor.shutdown()
        }
    }
    AndroidView(factory = { visualizacao }, modifier = modifier)
}
