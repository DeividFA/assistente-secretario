package com.deivid.secretario

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "gastos")
data class GastoLocal(
    @PrimaryKey val id: String = java.util.UUID.randomUUID().toString(),
    val data: String, val valor_centavos: Long, val descricao: String,
    val estabelecimento: String, val categoria: String, val forma: String,
    val origem: String, val confirmado: Boolean, val sincronizado: Boolean = false
)

@Dao
interface DadosGastos {
    @Query("SELECT * FROM gastos ORDER BY data DESC, id") fun observar(): Flow<List<GastoLocal>>
    @Query("SELECT * FROM gastos ORDER BY data,id") suspend fun todos(): List<GastoLocal>
    @Query("SELECT * FROM gastos WHERE sincronizado=0 LIMIT 50") suspend fun pendentes(): List<GastoLocal>
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun inserir(gasto: GastoLocal)
    @Update suspend fun atualizar(gasto: GastoLocal)
    @Query("UPDATE gastos SET sincronizado=1 WHERE id IN (:ids)") suspend fun sincronizados(ids: List<String>)
    @Query("SELECT COUNT(*) FROM gastos WHERE data=:data AND valor_centavos=:valor AND estabelecimento=:local AND origem=:origem")
    suspend fun duplicados(data: String, valor: Long, local: String, origem: String): Int
}

@Entity(tableName = "mensagens")
data class MensagemLocal(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val autor: String,
    val texto: String,
    val origem: String,
    val instante: Long = System.currentTimeMillis()
)

@Entity(tableName = "fatos_pendentes")
data class FatoPendente(@PrimaryKey(autoGenerate = true) val id: Long = 0, val texto: String)

@Dao
interface Dados {
    @Query("SELECT * FROM mensagens ORDER BY id") fun mensagens(): Flow<List<MensagemLocal>>
    @Query("SELECT * FROM mensagens ORDER BY id DESC LIMIT 20") suspend fun recentes(): List<MensagemLocal>
    @Insert suspend fun inserir(mensagem: MensagemLocal)
    @Insert suspend fun aprender(fato: FatoPendente)
    @Query("SELECT * FROM fatos_pendentes ORDER BY id LIMIT 50") suspend fun fatos(): List<FatoPendente>
    @Query("SELECT COUNT(*) FROM fatos_pendentes") fun quantidadeFatos(): Flow<Int>
    @Query("DELETE FROM fatos_pendentes WHERE id IN (:ids)") suspend fun confirmar(ids: List<Long>)
}

@Entity(tableName = "aprendizados")
data class AprendizadoLocal(@PrimaryKey val chave: String, val conteudo: String)

@Dao
interface DadosAprendizados {
    @Query("SELECT conteudo FROM aprendizados WHERE chave=:chave") suspend fun ler(chave: String): String?
    @Query("SELECT * FROM aprendizados WHERE chave LIKE :prefixo ORDER BY chave") suspend fun listar(prefixo: String): List<AprendizadoLocal>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun guardar(item: AprendizadoLocal)
    @Query("DELETE FROM aprendizados WHERE chave=:chave") suspend fun apagar(chave: String)
}

@Database(entities = [MensagemLocal::class, FatoPendente::class, GastoLocal::class, AprendizadoLocal::class], version = 3, exportSchema = true)
abstract class Banco : RoomDatabase() {
    abstract fun dados(): Dados
    abstract fun gastos(): DadosGastos
    abstract fun aprendizados(): DadosAprendizados
    companion object {
        val MIGRACAO_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `gastos` (`id` TEXT NOT NULL, `data` TEXT NOT NULL, `valor_centavos` INTEGER NOT NULL, `descricao` TEXT NOT NULL, `estabelecimento` TEXT NOT NULL, `categoria` TEXT NOT NULL, `forma` TEXT NOT NULL, `origem` TEXT NOT NULL, `confirmado` INTEGER NOT NULL, `sincronizado` INTEGER NOT NULL, PRIMARY KEY(`id`))")
            }
        }
        val MIGRACAO_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `aprendizados` (`chave` TEXT NOT NULL, `conteudo` TEXT NOT NULL, PRIMARY KEY(`chave`))")
            }
        }
        fun abrir(contexto: Context): Banco = Room.databaseBuilder(contexto, Banco::class.java, "secretario.db")
            .addMigrations(MIGRACAO_1_2, MIGRACAO_2_3).build()
    }
}
