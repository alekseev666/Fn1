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
                    if data.get('pairs'):
                        # Сортируем пары по ликвидности (по убыванию)
                        pairs = sorted(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
                        return pairs[0] if pairs else None
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
            # Получаем информацию о токене и его парах
            async with self.session.get(f"{self.base_url}/dex/tokens/{token_address}") as response:
                if response.status != 200:
                    return []
                
                data = await response.json()
                pairs = data.get('pairs', [])
                
                if not pairs:
                    return []

                # Сортируем пары по ликвидности
                pairs = sorted(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
                
                # Берем самую ликвидную пару
                pair = pairs[0]
                chain_id = pair['chainId']
                pair_address = pair['pairAddress']

                # Получаем транзакции для пары
                async with self.session.get(f"{self.base_url}/dex/pairs/{chain_id}/{pair_address}") as response:
                    if response.status != 200:
                        return []

                    pair_data = await response.json()
                    if not pair_data.get('pairs'):
                        return []

                    pair_info = pair_data['pairs'][0]
                    transactions = []

                    # Получаем статистику транзакций
                    txns = pair_info.get('txns', {})
                    volume = pair_info.get('volume', {})
                    
                    # Формируем транзакции на основе статистики
                    for time_frame, txn_data in txns.items():
                        if 'buys' in txn_data:
                            for _ in range(txn_data['buys']):
                                transactions.append({
                                    'type': 'buy',
                                    'amountUsd': volume.get(time_frame, 0) / (txn_data['buys'] + txn_data.get('sells', 0)),
                                    'timestamp': int(datetime.now().timestamp())
                                })
                        if 'sells' in txn_data:
                            for _ in range(txn_data['sells']):
                                transactions.append({
                                    'type': 'sell',
                                    'amountUsd': volume.get(time_frame, 0) / (txn_data['buys'] + txn_data.get('sells', 0)),
                                    'timestamp': int(datetime.now().timestamp())
                                })

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