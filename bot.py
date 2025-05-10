import os
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
import json
from dexscreener import DexScreenerAPI

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '60'))
MIN_TRANSACTION_AMOUNT = float(os.getenv('MIN_TRANSACTION_AMOUNT', '1000'))

class DexScreenerBot:
    def __init__(self):
        self.watched_tokens = {}  # Словарь для хранения отслеживаемых токенов
        self.user_settings = {}   # Настройки пользователей
        self.last_check = {}      # Время последней проверки для каждого токена

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        await update.message.reply_text(
            "Привет! Я бот для мониторинга транзакций в DexScreener.\n"
            "Доступные команды:\n"
            "/watch <адрес_токена> - Начать отслеживание токена\n"
            "/unwatch <адрес_токена> - Прекратить отслеживание\n"
            "/list - Показать список отслеживаемых токенов\n"
            "/settings - Настройки мониторинга\n"
            "/last_tx <адрес_токена> - Показать последние транзакции токена\n"
            "/help - Показать это сообщение"
        )

    async def watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /watch"""
        if not context.args:
            await update.message.reply_text("Пожалуйста, укажите адрес токена для отслеживания")
            return

        token_address = context.args[0]
        user_id = update.effective_user.id

        # Проверка существования токена
        async with DexScreenerAPI() as api:
            token_info = await api.get_token_info(token_address)
            if not token_info:
                await update.message.reply_text("Токен не найден. Проверьте адрес и попробуйте снова.")
                return

        if user_id not in self.watched_tokens:
            self.watched_tokens[user_id] = set()
            self.user_settings[user_id] = {
                'min_amount': MIN_TRANSACTION_AMOUNT,
                'transaction_type': None
            }
        
        self.watched_tokens[user_id].add(token_address)
        self.last_check[token_address] = datetime.now()
        
        await update.message.reply_text(
            f"Токен {token_address} добавлен в список отслеживания\n"
            f"Текущие настройки:\n"
            f"Минимальная сумма: ${self.user_settings[user_id]['min_amount']}\n"
            f"Тип транзакций: {'Все' if not self.user_settings[user_id]['transaction_type'] else self.user_settings[user_id]['transaction_type']}"
        )

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /settings"""
        user_id = update.effective_user.id
        if user_id not in self.user_settings:
            await update.message.reply_text("Сначала добавьте токен для отслеживания командой /watch")
            return

        if not context.args:
            # Показать текущие настройки
            settings = self.user_settings[user_id]
            await update.message.reply_text(
                "Текущие настройки:\n"
                f"Минимальная сумма: ${settings['min_amount']}\n"
                f"Тип транзакций: {'Все' if not settings['transaction_type'] else settings['transaction_type']}\n\n"
                "Для изменения настроек используйте:\n"
                "/settings min <сумма> - Установить минимальную сумму\n"
                "/settings type <buy/sell> - Установить тип транзакций"
            )
            return

        if len(context.args) < 2:
            await update.message.reply_text("Неверный формат команды")
            return

        setting_type = context.args[0].lower()
        value = context.args[1].lower()

        if setting_type == 'min':
            try:
                amount = float(value)
                self.user_settings[user_id]['min_amount'] = amount
                await update.message.reply_text(f"Минимальная сумма установлена: ${amount}")
            except ValueError:
                await update.message.reply_text("Неверное значение суммы")
        elif setting_type == 'type':
            if value in ['buy', 'sell']:
                self.user_settings[user_id]['transaction_type'] = value
                await update.message.reply_text(f"Тип транзакций установлен: {value}")
            else:
                await update.message.reply_text("Тип транзакций должен быть 'buy' или 'sell'")
        else:
            await update.message.reply_text("Неизвестный параметр настроек")

    async def check_transactions(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверка транзакций для всех отслеживаемых токенов"""
        async with DexScreenerAPI() as api:
            for user_id, tokens in self.watched_tokens.items():
                settings = self.user_settings[user_id]
                for token_address in tokens:
                    transactions = await api.get_recent_transactions(
                        token_address,
                        min_amount=settings['min_amount'],
                        transaction_type=settings['transaction_type'],
                        time_window=CHECK_INTERVAL
                    )

                    for tx in transactions:
                        # Формируем сообщение о транзакции
                        message = (
                            f"🔔 Новая транзакция!\n"
                            f"Токен: {token_address}\n"
                            f"Тип: {tx['type']}\n"
                            f"Сумма: ${float(tx['amountUsd']):.2f}\n"
                            f"Время: {datetime.fromtimestamp(tx['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        
                        try:
                            await context.bot.send_message(chat_id=user_id, text=message)
                        except Exception as e:
                            logger.error(f"Error sending message to user {user_id}: {e}")

    async def unwatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /unwatch"""
        if not context.args:
            await update.message.reply_text("Пожалуйста, укажите адрес токена для прекращения отслеживания")
            return

        token_address = context.args[0]
        user_id = update.effective_user.id

        if user_id in self.watched_tokens and token_address in self.watched_tokens[user_id]:
            self.watched_tokens[user_id].remove(token_address)
            if token_address in self.last_check:
                del self.last_check[token_address]
            await update.message.reply_text(f"Токен {token_address} удален из списка отслеживания")
        else:
            await update.message.reply_text("Этот токен не отслеживается")

    async def list_watched(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /list"""
        user_id = update.effective_user.id
        if user_id not in self.watched_tokens or not self.watched_tokens[user_id]:
            await update.message.reply_text("У вас нет отслеживаемых токенов")
            return

        settings = self.user_settings[user_id]
        tokens_list = "\n".join(self.watched_tokens[user_id])
        await update.message.reply_text(
            f"Отслеживаемые токены:\n{tokens_list}\n\n"
            f"Текущие настройки:\n"
            f"Минимальная сумма: ${settings['min_amount']}\n"
            f"Тип транзакций: {'Все' if not settings['transaction_type'] else settings['transaction_type']}"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        await self.start(update, context)

    async def last_tx(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /last_tx"""
        if not context.args:
            await update.message.reply_text("Пожалуйста, укажите адрес токена для получения последних транзакций")
            return

        token_address = context.args[0]
        async with DexScreenerAPI() as api:
            try:
                # Получаем информацию о токене и его парах
                async with api.session.get(f"{api.base_url}/dex/tokens/{token_address}") as response:
                    if response.status != 200:
                        await update.message.reply_text("Ошибка при получении информации о токене.")
                        return
                    
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    
                    if not pairs:
                        await update.message.reply_text("Пары для этого токена не найдены.")
                        return

                    # Сортируем пары по ликвидности
                    pairs = sorted(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
                    
                    # Берем самую ликвидную пару
                    pair = pairs[0]
                    chain_id = pair['chainId']
                    pair_address = pair['pairAddress']
                    pair_url = pair.get('url', '')
                    base_token = pair.get('baseToken', {})
                    quote_token = pair.get('quoteToken', {})

                    # Получаем детальную информацию о паре
                    async with api.session.get(f"{api.base_url}/dex/pairs/{chain_id}/{pair_address}") as response:
                        if response.status != 200:
                            await update.message.reply_text("Не удалось получить информацию о паре.")
                            return

                        pair_data = await response.json()
                        if not pair_data.get('pairs'):
                            await update.message.reply_text("Информация о паре не найдена.")
                            return

                        pair_info = pair_data['pairs'][0]
                        
                        # Формируем сообщение с информацией о паре
                        message = (
                            f"💱 Пара: {base_token.get('symbol', '')}/{quote_token.get('symbol', '')}\n"
                            f"🔗 Ссылка: {pair_url}\n"
                            f"💰 Цена: ${float(pair_info.get('priceUsd', 0)):.6f}\n"
                            f"💧 Ликвидность: ${float(pair_info.get('liquidity', {}).get('usd', 0)):,.2f}\n\n"
                            f"📊 Статистика транзакций:\n"
                        )

                        # Добавляем статистику по временным интервалам
                        txns = pair_info.get('txns', {})
                        for time_frame, txn_data in txns.items():
                            buys = txn_data.get('buys', 0)
                            sells = txn_data.get('sells', 0)
                            message += f"{time_frame}: 🟢 {buys} покупок, 🔴 {sells} продаж\n"

                        await update.message.reply_text(message)

            except Exception as e:
                logger.error(f"Error in last_tx: {e}")
                await update.message.reply_text(f"Произошла ошибка при получении информации: {str(e)}")

def main():
    """Запуск бота"""
    bot = DexScreenerBot()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("watch", bot.watch))
    application.add_handler(CommandHandler("unwatch", bot.unwatch))
    application.add_handler(CommandHandler("list", bot.list_watched))
    application.add_handler(CommandHandler("settings", bot.settings))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("last_tx", bot.last_tx))

    # Добавляем задачу проверки транзакций
    application.job_queue.run_repeating(bot.check_transactions, interval=CHECK_INTERVAL)

    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 