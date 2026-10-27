package com.deivid.secretario

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.*
import android.speech.tts.TextToSpeech
import java.util.Locale

class Voz(private val contexto: Context, private val transcrever: (String) -> Unit, private val aviso: (String) -> Unit) {
    private var pronta = false
    private val fala = TextToSpeech(contexto) { status ->
        if (status == TextToSpeech.SUCCESS) {
            pronta = true
            configurarIdioma()
        } else aviso("Síntese de voz indisponível")
    }
    private var reconhecimento: SpeechRecognizer? = null

    private fun configurarIdioma() {
        val resultado = fala.setLanguage(Locale.forLanguageTag("pt-BR"))
        if (resultado < TextToSpeech.LANG_AVAILABLE) { pronta = false; aviso("Instale uma voz pt-BR nas configurações do Android") }
    }

    fun ouvir() {
        if (!SpeechRecognizer.isRecognitionAvailable(contexto)) { aviso("Reconhecimento de voz indisponível"); return }
        fala.stop()
        reconhecimento?.destroy()
        val local = android.os.Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(contexto)
        val reconhecedor = if (local) SpeechRecognizer.createOnDeviceSpeechRecognizer(contexto)
            else SpeechRecognizer.createSpeechRecognizer(contexto)
        reconhecimento = reconhecedor
        reconhecedor.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { aviso("Ouvindo…") }
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onError(error: Int) { aviso("Não consegui ouvir (código $error). Tente novamente ou digite.") }
            override fun onResults(results: Bundle?) {
                results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(transcrever)
            }
            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })
        reconhecedor.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "pt-BR")
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        })
    }

    fun dizer(texto: String) {
        if (pronta) fala.speak(texto.take(TextToSpeech.getMaxSpeechInputLength()), TextToSpeech.QUEUE_ADD, null, "resposta")
    }
    fun silenciar() { reconhecimento?.cancel(); fala.stop() }
    fun fechar() { reconhecimento?.destroy(); fala.shutdown() }
}
