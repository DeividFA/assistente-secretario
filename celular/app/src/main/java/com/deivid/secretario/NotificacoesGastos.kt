package com.deivid.secretario

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.coroutines.*

class NotificacoesGastos : NotificationListenerService() {
    private val escopo = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val banco by lazy { Banco.abrir(this) }
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val preferencias = PreferenciasGastos(this)
        // Filtrar o pacote antes de sequer consultar os extras.
        if (!preferencias.notificacoes || sbn.packageName !in preferencias.apps()) return
        val rotulo = runCatching { packageManager.getApplicationInfo(sbn.packageName, 0)
            .loadLabel(packageManager).toString() }.getOrDefault("")
        if (!BloqueioFinanceiro().bloqueado(sbn.packageName, rotulo)) return
        val extras = sbn.notification.extras
        val texto = listOf(extras.getCharSequence(Notification.EXTRA_TITLE),
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))
            .filterNotNull().joinToString(" ").take(12000)
        val data = java.time.Instant.ofEpochMilli(sbn.postTime).atZone(java.time.ZoneId.systemDefault()).toLocalDate()
        val item = runCatching { ParseGastos.notificacao(texto, data) }.getOrNull() ?: return
        val id = java.util.UUID.nameUUIDFromBytes("${sbn.key}:${sbn.postTime}".toByteArray(Charsets.UTF_8)).toString()
        escopo.launch {
            GastosCelular(banco.gastos(), preferencias).guardar(item.copy(
                categoria = preferencias.categoria(item.estabelecimento) ?: item.categoria), false, id)
        }
    }
    override fun onDestroy() { escopo.cancel(); banco.close(); super.onDestroy() }
}
