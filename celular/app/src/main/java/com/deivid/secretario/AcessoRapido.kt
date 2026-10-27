package com.deivid.secretario

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.RemoteViews

private fun intencao(contexto: Context) = Intent(contexto, MainActivity::class.java)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("ouvir", true)

private fun pendente(contexto: Context): PendingIntent = PendingIntent.getActivity(contexto, 1, intencao(contexto),
    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

class BlocoSecretario : TileService() {
    override fun onStartListening() { qsTile?.apply { state = Tile.STATE_INACTIVE; updateTile() } }
    @Suppress("DEPRECATION")
    override fun onClick() {
        super.onClick()
        unlockAndRun {
            if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(pendente(this))
            else startActivityAndCollapse(intencao(this))
        }
    }
}

class WidgetSecretario : AppWidgetProvider() {
    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        appWidgetIds.forEach { id ->
            val visualizacao = RemoteViews(context.packageName, R.layout.widget_secretario)
            visualizacao.setOnClickPendingIntent(R.id.abrir_secretario, pendente(context))
            appWidgetManager.updateAppWidget(id, visualizacao)
        }
    }
}
