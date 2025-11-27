import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import pandas as pd
import ta
import requests
from datetime import datetime
import json
import os
from binance.client import Client

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = "8506038424:AAH4LSquaNRRB11aolVkp5J1-I27GXO4zao"

# Configuración APIs
client = Client()
CRYPTOPANIC_API_KEY = "tu_cryptopanic_key"

# 🏦 Simulador de Trading
class SimuladorTrading:
    def __init__(self, capital_inicial=1000):
        self.capital = capital_inicial
        self.capital_inicial = capital_inicial
        self.posicion_abierta = False
        self.precio_entrada = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.operaciones = []
        self.archivo_registro = "registro_operaciones.json"
        self.cargar_registro()
    
    def cargar_registro(self):
        if os.path.exists(self.archivo_registro):
            with open(self.archivo_registro, 'r') as f:
                data = json.load(f)
                self.operaciones = data.get('operaciones', [])
                self.capital = data.get('capital_actual', self.capital)
    
    def guardar_registro(self):
        data = {
            'capital_inicial': self.capital_inicial,
            'capital_actual': self.capital,
            'total_operaciones': len(self.operaciones),
            'operaciones_ganadoras': len([op for op in self.operaciones if op.get('ganancia', 0) > 0]),
            'operaciones_perdedoras': len([op for op in self.operaciones if op.get('ganancia', 0) <= 0]),
            'operaciones': self.operaciones
        }
        with open(self.archivo_registro, 'w') as f:
            json.dump(data, f, indent=2)
    
    def ejecutar_operacion(self, accion, precio_actual):
        """Ejecutar operación de compra/venta automáticamente"""
        if accion == "🟢 COMPRA" and not self.posicion_abierta:
            # COMPRAR
            self.posicion_abierta = True
            self.precio_entrada = precio_actual
            self.stop_loss = precio_actual * 0.97  # -3%
            self.take_profit = precio_actual * 1.06  # +6%
            
            operacion = {
                'tipo': 'COMPRA',
                'precio': precio_actual,
                'fecha': datetime.now().isoformat(),
                'capital_antes': self.capital
            }
            self.operaciones.append(operacion)
            self.guardar_registro()
            return f"🟢 COMPRA ejecutada a ${precio_actual:.2f}"
        
        elif accion == "🔴 VENDE" and self.posicion_abierta:
            # VENDER
            ganancia = precio_actual - self.precio_entrada
            self.capital += ganancia
            self.posicion_abierta = False
            
            operacion = {
                'tipo': 'VENTA',
                'precio_entrada': self.precio_entrada,
                'precio_salida': precio_actual,
                'ganancia': ganancia,
                'ganancia_porcentaje': (ganancia / self.precio_entrada) * 100,
                'fecha': datetime.now().isoformat(),
                'capital_despues': self.capital
            }
            self.operaciones.append(operacion)
            self.guardar_registro()
            
            resultado = "GANANCIA" if ganancia > 0 else "PÉRDIDA"
            return f"🔴 VENTA ejecutada a ${precio_actual:.2f} | {resultado}: ${ganancia:.2f}"
        
        return None
    
    def verificar_stop_loss_take_profit(self, precio_actual):
        """Verificar si hay que salir por SL o TP"""
        if not self.posicion_abierta:
            return None
        
        if precio_actual <= self.stop_loss:
            return self.ejecutar_operacion("🔴 VENDE", precio_actual)
        
        if precio_actual >= self.take_profit:
            return self.ejecutar_operacion("🔴 VENDE", precio_actual)
        
        return None
    
    def obtener_estadisticas(self):
        if not self.operaciones:
            return "📊 Sin operaciones aún"
        
        ops_ganadoras = [op for op in self.operaciones if op.get('ganancia', 0) > 0]
        ops_perdedoras = [op for op in self.operaciones if op.get('ganancia', 0) <= 0]
        
        win_rate = (len(ops_ganadoras) / len(self.operaciones)) * 100 if self.operaciones else 0
        ganancia_total = sum(op.get('ganancia', 0) for op in self.operaciones)
        ganancia_porcentaje = ((self.capital - self.capital_inicial) / self.capital_inicial) * 100
        
        return {
            'total_operaciones': len(self.operaciones),
            'operaciones_ganadoras': len(ops_ganadoras),
            'operaciones_perdedoras': len(ops_perdedoras),
            'win_rate': win_rate,
            'ganancia_total': ganancia_total,
            'ganancia_porcentaje': ganancia_porcentaje,
            'capital_actual': self.capital
        }

# Instanciar simulador
simulador = SimuladorTrading()

# Funciones de trading
def get_crypto_data(symbol="BTCUSDT", interval="1h", limit=50):
    try:
        klines = client.get_historical_klines(symbol, interval, limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
            'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume',
            'taker_buy_quote_asset_volume', 'ignore'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"❌ Error datos: {e}")
        return None

def calculate_indicators(df):
    df['sma_20'] = ta.trend.SMAIndicator(df['close'], window=20).sma_indicator()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    return df

def get_trading_action(df):
    latest = df.iloc[-1]
    previous = df.iloc[-2]
    
    buy_signals = 0
    
    if latest['close'] > latest['sma_20']: buy_signals += 1
    if latest['rsi'] < 30: buy_signals += 1
    elif latest['rsi'] > 70: buy_signals += 0
    else: buy_signals += 0.5
    if latest['macd'] > latest['macd_signal'] and previous['macd'] <= previous['macd_signal']: buy_signals += 1
    
    if buy_signals >= 2: return "🟢 COMPRA"
    elif buy_signals <= 1: return "🔴 VENDE"
    else: return "🟡 ESPERA"

# 🤖 TRADING AUTOMÁTICO
async def trading_automatico(context: ContextTypes.DEFAULT_TYPE):
    """Ejecutar trading automático cada 3 minutos"""
    try:
        print(f"🔄 [{datetime.now().strftime('%H:%M:%S')}] Ejecutando trading automático...")
        
        # Obtener datos
        df = get_crypto_data("BTCUSDT", "1h", 50)
        if df is None:
            print("❌ No se pudieron obtener datos")
            return
            
        # Calcular indicadores
        df = calculate_indicators(df)
        accion = get_trading_action(df)
        precio = df.iloc[-1]['close']
        rsi = df.iloc[-1]['rsi']
        
        print(f"📊 Señal: {accion} | Precio: ${precio:.2f} | RSI: {rsi:.1f}")
        
        # EJECUTAR OPERACIÓN
        resultado_operacion = simulador.ejecutar_operacion(accion, precio)
        sl_tp_resultado = simulador.verificar_stop_loss_take_profit(precio)
        
        # REGISTRAR EN LOG
        if resultado_operacion:
            print(f"✅ OPERACIÓN: {resultado_operacion}")
        if sl_tp_resultado:
            print(f"⚡ SL/TP: {sl_tp_resultado}")
        
        # SOLO NOTIFICAR SI HUBO OPERACIÓN
        if resultado_operacion or sl_tp_resultado:
            mensaje = f"🤖 **OPERACIÓN AUTOMÁTICA**\n\n"
            
            if resultado_operacion:
                mensaje += f"🎯 {resultado_operacion}\n"
            
            if sl_tp_resultado:
                mensaje += f"⚡ {sl_tp_resultado}\n"
            
            mensaje += f"💰 BTC: ${precio:.2f}\n"
            mensaje += f"🎯 RSI: {rsi:.1f}\n"
            mensaje += f"📈 Señal: {accion}\n"
            mensaje += f"💼 Capital: ${simulador.capital:.2f}"
            
            # Enviar a todos los chats activos
            jobs = context.job_queue.get_jobs_by_name('trading_automatico')
            for job in jobs:
                try:
                    await context.bot.send_message(chat_id=job.chat_id, text=mensaje, parse_mode='Markdown')
                except Exception as e:
                    print(f"❌ Error enviando mensaje: {e}")
                    
    except Exception as e:
        print(f"❌ Error en trading automático: {e}")

async def iniciar_autotrading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /auto - Iniciar trading automático"""
    chat_id = update.effective_chat.id
    
    # VERIFICAR que job_queue existe
    if context.job_queue is None:
        await update.message.reply_text("❌ Error: JobQueue no inicializado")
        return
    
    # Detener trabajos existentes
    jobs = context.job_queue.get_jobs_by_name('trading_automatico')
    for job in jobs:
        if job.chat_id == chat_id:
            job.schedule_removal()
    
    # Programar nuevo trabajo
    context.job_queue.run_repeating(
        trading_automatico, 
        interval=180,  # 3 minutos
        first=10,      # Empezar en 10 segundos
        chat_id=chat_id,
        name='trading_automatico'
    )
    
    await update.message.reply_text(
        "✅ **TRADING AUTOMÁTICO ACTIVADO**\n\n"
        "🤖 Operando cada 3 minutos\n"
        "💰 Notificaciones en tiempo real\n"
        "📈 Señales: COMPRA/VENTA/ESPERA\n"
        "⏹️ Para detener: /stop\n\n"
        "🔄 Primera operación en 10 segundos..."
    )
    print(f"🔰 Trading automático activado para chat: {chat_id}")

async def detener_autotrading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /stop - Detener trading automático"""
    chat_id = update.effective_chat.id
    
    if context.job_queue is None:
        await update.message.reply_text("❌ Error: JobQueue no inicializado")
        return
        
    jobs = context.job_queue.get_jobs_by_name('trading_automatico')
    jobs_removed = 0
    
    for job in jobs:
        if job.chat_id == chat_id:
            job.schedule_removal()
            jobs_removed += 1
    
    if jobs_removed > 0:
        await update.message.reply_text("⏹️ **TRADING AUTOMÁTICO DETENIDO**")
        print(f"🛑 Trading automático detenido para chat: {chat_id}")
    else:
        await update.message.reply_text("❌ No hay trading automático activo")

async def debug_autotrading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /debug - Ver estado del sistema"""
    chat_id = update.effective_chat.id
    
    # Verificar job_queue
    job_status = "✅ JobQueue activo" if context.job_queue else "❌ JobQueue no disponible"
    
    # Verificar jobs activos
    jobs_count = 0
    if context.job_queue:
        jobs = context.job_queue.get_jobs_by_name('trading_automatico')
        jobs_count = len([job for job in jobs if job.chat_id == chat_id])
    
    # Verificar datos de mercado
    df = get_crypto_data("BTCUSDT", "1h", 50)
    if df is not None:
        df = calculate_indicators(df)
        accion = get_trading_action(df)
        precio = df.iloc[-1]['close']
        rsi = df.iloc[-1]['rsi']
        mercado_info = f"💰 BTC: ${precio:.2f} | RSI: {rsi:.1f} | Señal: {accion}"
    else:
        mercado_info = "❌ Error obteniendo datos mercado"
    
    mensaje = f"""
🐛 **DEBUG DEL SISTEMA**

{job_status}
🤖 Jobs automáticos activos: {jobs_count}
{mercado_info}

💼 **SIMULADOR:**
• Capital: ${simulador.capital:.2f}
• Operaciones: {len(simulador.operaciones)}
• Posición: {'🟢 ABIERTA' if simulador.posicion_abierta else '🔴 CERRADA'}
• Última op: {simulador.operaciones[-1]['tipo'] if simulador.operaciones else 'Ninguna'}
"""

    await update.message.reply_text(mensaje)

# COMANDOS DE TRADING
async def trading_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /trading - Mostrar estado actual"""
    # Obtener datos actuales
    df = get_crypto_data("BTCUSDT", "1h", 50)
    if df is None:
        await update.message.reply_text("❌ Error obteniendo datos del mercado")
        return
    
    df = calculate_indicators(df)
    accion_actual = get_trading_action(df)
    precio_actual = df.iloc[-1]['close']
    rsi_actual = df.iloc[-1]['rsi']
    
    # EJECUTAR OPERACIÓN
    resultado_operacion = simulador.ejecutar_operacion(accion_actual, precio_actual)
    sl_tp_resultado = simulador.verificar_stop_loss_take_profit(precio_actual)
    
    # Obtener estadísticas
    stats = simulador.obtener_estadisticas()
    
    mensaje = f"""
📊 **ESTADO DE TRADING**

💰 **Precio BTC:** ${precio_actual:.2f}
🎯 **RSI:** {rsi_actual:.1f}
📈 **Señal Actual:** {accion_actual}

💼 **SIMULACIÓN:**
• Capital: ${simulador.capital:.2f}
• Posición: {'🟢 ABIERTA' if simulador.posicion_abierta else '🔴 CERRADA'}
"""
    
    if simulador.posicion_abierta:
        ganancia_actual = precio_actual - simulador.precio_entrada
        mensaje += f"• Ganancia actual: ${ganancia_actual:.2f}\n"
        mensaje += f"• SL: ${simulador.stop_loss:.2f} | TP: ${simulador.take_profit:.2f}\n"

    if isinstance(stats, dict):
        mensaje += f"""
📈 **ESTADÍSTICAS:**
• Operaciones: {stats['total_operaciones']}
• Win Rate: {stats['win_rate']:.1f}%
• Ganancia: {stats['ganancia_porcentaje']:.1f}%
• Capital: ${stats['capital_actual']:.2f}
"""
    
    # MOSTRAR RESULTADO DE OPERACIÓN
    if resultado_operacion:
        mensaje += f"\n🎯 {resultado_operacion}"
    
    if sl_tp_resultado:
        mensaje += f"\n⚡ {sl_tp_resultado}"

    keyboard = [
        [InlineKeyboardButton("🔄 Actualizar", callback_data="refresh_trading")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="detailed_stats")],
        [InlineKeyboardButton("🤖 Activar Auto", callback_data="activar_auto")],
        [InlineKeyboardButton("⏹️ Detener Auto", callback_data="detener_auto")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode='Markdown')

async def analizar_mercado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /analizar - Análisis completo del mercado"""
    df = get_crypto_data("BTCUSDT", "1h", 50)
    if df is None:
        await update.message.reply_text("❌ Error obteniendo datos")
        return
    
    df = calculate_indicators(df)
    latest = df.iloc[-1]
    
    mensaje = f"""
🔍 **ANÁLISIS TÉCNICO BTC**

💰 Precio: ${latest['close']:.2f}
📈 SMA 20: ${latest['sma_20']:.2f}
🎯 RSI: {latest['rsi']:.1f}
🌈 MACD: {latest['macd']:.4f}

📊 **INTERPRETACIÓN:**
"""
    
    # Análisis de tendencia
    if latest['close'] > latest['sma_20']:
        mensaje += "• 📈 Tendencia: ALCISTA\n"
    else:
        mensaje += "• 📉 Tendencia: BAJISTA\n"
    
    # Análisis RSI
    if latest['rsi'] < 30:
        mensaje += "• 🟢 RSI: SOBREVENDIDO (Posible compra)\n"
    elif latest['rsi'] > 70:
        mensaje += "• 🔴 RSI: SOBRECOMPRADO (Posible venta)\n"
    else:
        mensaje += "• ⚪ RSI: NEUTRAL\n"
    
    # Señal actual
    accion = get_trading_action(df)
    mensaje += f"• 🎯 Señal: {accion}\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def simulacion_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /simulacion - Estado completo de la simulación"""
    stats = simulador.obtener_estadisticas()
    
    if isinstance(stats, dict):
        mensaje = f"""
💰 **ESTADO DE SIMULACIÓN**

• Capital inicial: ${simulador.capital_inicial:.2f}
• Capital actual: ${stats['capital_actual']:.2f}
• Ganancia/Pérdida: ${stats['ganancia_total']:.2f}
• Rendimiento: {stats['ganancia_porcentaje']:.1f}%

📊 **OPERACIONES:**
• Totales: {stats['total_operaciones']}
• Ganadoras: {stats['operaciones_ganadoras']}
• Perdedoras: {stats['operaciones_perdedoras']}
• Win Rate: {stats['win_rate']:.1f}%

💼 **POSICIÓN ACTUAL:**
• Estado: {'🟢 ABIERTA' if simulador.posicion_abierta else '🔴 CERRADA'}
"""
        if simulador.posicion_abierta:
            df = get_crypto_data()
            if df is not None:
                precio_actual = df.iloc[-1]['close']
                ganancia_actual = precio_actual - simulador.precio_entrada
                mensaje += f"• Entrada: ${simulador.precio_entrada:.2f}\n"
                mensaje += f"• Ganancia actual: ${ganancia_actual:.2f}\n"
                mensaje += f"• SL: ${simulador.stop_loss:.2f}\n"
                mensaje += f"• TP: ${simulador.take_profit:.2f}\n"
    else:
        mensaje = stats
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def operaciones_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /operaciones - Historial de operaciones"""
    if not simulador.operaciones:
        await update.message.reply_text("📭 No hay operaciones registradas")
        return
    
    mensaje = "📋 **HISTORIAL DE OPERACIONES**\n\n"
    for i, op in enumerate(simulador.operaciones[-10:], 1):
        if op['tipo'] == 'COMPRA':
            fecha = datetime.fromisoformat(op['fecha']).strftime('%H:%M')
            mensaje += f"{i}. 🟢 COMPRA - ${op['precio']:,.2f} - {fecha}\n"
        else:
            fecha = datetime.fromisoformat(op['fecha']).strftime('%H:%M')
            resultado = "🟢" if op['ganancia'] > 0 else "🔴"
            mensaje += f"{i}. 🔴 VENTA - ${op['precio_salida']:,.2f} - {resultado} ${op['ganancia']:,.2f} - {fecha}\n"
    
    await update.message.reply_text(mensaje)

async def handle_trading_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar callbacks de trading"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "refresh_trading":
        await trading_command(update, context)
    
    elif query.data == "detailed_stats":
        stats = simulador.obtener_estadisticas()
        if isinstance(stats, dict):
            mensaje = f"""
📊 **ESTADÍSTICAS DETALLADAS**

💰 Capital Inicial: ${simulador.capital_inicial:.2f}
💰 Capital Actual: ${stats['capital_actual']:.2f}
📈 Rendimiento: {stats['ganancia_porcentaje']:.1f}%

🎯 Operaciones: {stats['total_operaciones']}
🟢 Ganadoras: {stats['operaciones_ganadoras']}
🔴 Perdedoras: {stats['operaciones_perdedoras']}
📊 Win Rate: {stats['win_rate']:.1f}%

💵 Ganancia Total: ${stats['ganancia_total']:.2f}
"""
            await query.edit_message_text(mensaje, parse_mode='Markdown')
    
    elif query.data == "activar_auto":
        await iniciar_autotrading(update, context)
    
    elif query.data == "detener_auto":
        await detener_autotrading(update, context)

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    keyboard = [
        [InlineKeyboardButton("📊 Trading", callback_data="trading_menu")],
        [InlineKeyboardButton("💰 Simulación", callback_data="simulacion_menu")],
        [InlineKeyboardButton("📈 Analizar", callback_data="analyze_btc")],
        [InlineKeyboardButton("🤖 Activar Auto", callback_data="activar_auto")],
        [InlineKeyboardButton("🐛 Debug", callback_data="debug_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f'¡Hola {user.first_name}! 👋\n\n'
        f'🤖 **BOT DE TRADING AUTOMÁTICO**\n\n'
        f'💰 Capital: $1,000 virtuales\n'
        f'⏰ Operaciones cada 3 minutos\n'
        f'📈 Señales en tiempo real\n\n'
        f'Selecciona una opción:',
        reply_markup=reply_markup
    )

# Manejar mensajes de texto
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user = update.message.from_user
    
    respuesta = f"""
👋 Hola {user.first_name}!

Usa estos comandos:
/start - Menú principal
/trading - Estado y operaciones
/simulacion - Estado de $1,000
/operaciones - Historial
/analizar - Análisis técnico
/auto - 🤖 Trading automático
/stop - ⏹️ Detener automático
/debug - 🐛 Diagnóstico
"""
    await update.message.reply_text(respuesta)

# Manejar selecciones del menú
async def handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "trading_menu":
        await trading_command(update, context)
    elif query.data == "simulacion_menu":
        await simulacion_command(update, context)
    elif query.data == "analyze_btc":
        await analizar_mercado_command(update, context)
    elif query.data == "activar_auto":
        await iniciar_autotrading(update, context)
    elif query.data == "debug_info":
        await debug_autotrading(update, context)

def main():
    # Inicializar aplicación
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers principales
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("trading", trading_command))
    application.add_handler(CommandHandler("simulacion", simulacion_command))
    application.add_handler(CommandHandler("operaciones", operaciones_command))
    application.add_handler(CommandHandler("analizar", analizar_mercado_command))
    application.add_handler(CommandHandler("auto", iniciar_autotrading))
    application.add_handler(CommandHandler("stop", detener_autotrading))
    application.add_handler(CommandHandler("debug", debug_autotrading))
    
    # Handlers de callbacks
    application.add_handler(CallbackQueryHandler(handle_selection, pattern="^(trading_menu|simulacion_menu|analyze_btc|activar_auto|debug_info)$"))
    application.add_handler(CallbackQueryHandler(handle_trading_callback, pattern="^(refresh_trading|detailed_stats|activar_auto|detener_auto)$"))
    
    # Handler para mensajes de texto
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot de Trading AUTOMÁTICO iniciado!")
    print("📍 Comandos: /start, /trading, /simulacion, /operaciones, /analizar")
    print("🤖 AUTOMÁTICO: /auto (cada 3 minutos) - /stop (detener)")
    print("🐛 DEBUG: /debug (diagnóstico)")
    print("💰 Simulación activa con $1,000 virtuales")
    
    
    application.run_polling()

if __name__ == "__main__":
    main()