import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class DexScreenerAPI:
    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest"
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_token_info(self, token_address: str) -> Optional[Dict]:
        """Получение информации о токене"""
        try:
            async with self.session.get(f"{self.base_url}/dex/tokens/{token_address}") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('pairs', [])[0] if data.get('pairs') else None
                return None
        except Exception as e:
            logger.error(f"Error getting token info: {e}")
            return None

    async def get_recent_transactions(self, token_address: str, 
                                    min_amount: float = 0,
                                    transaction_type: str = None,
                                    time_window: int = 3600) -> List[Dict]:
        """
        Получение последних транзакций для токена
        
        Args:
            token_address: Адрес токена
            min_amount: Минимальная сумма транзакции в USD
            transaction_type: Тип транзакции ('buy' или 'sell')
            time_window: Временное окно в секундах для поиска транзакций
        """
        try:
            # Получаем информацию о токене
            token_info = await self.get_token_info(token_address)
            if not token_info:
                return []

            # Получаем транзакции
            async with self.session.get(
                f"{self.base_url}/dex/pairs/{token_info['chainId']}/{token_info['pairAddress']}/transactions"
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                transactions = data.get('transactions', [])

                # Фильтруем транзакции
                filtered_transactions = []
                for tx in transactions:
                    # Проверяем временное окно
                    tx_time = datetime.fromtimestamp(tx['timestamp'])
                    if datetime.now() - tx_time > timedelta(seconds=time_window):
                        continue

                    # Проверяем тип транзакции
                    if transaction_type and tx['type'].lower() != transaction_type.lower():
                        continue

                    # Проверяем сумму
                    if float(tx['amountUsd']) < min_amount:
                        continue

                    filtered_transactions.append(tx)

                return filtered_transactions

        except Exception as e:
            logger.error(f"Error getting transactions: {e}")
            return [] 