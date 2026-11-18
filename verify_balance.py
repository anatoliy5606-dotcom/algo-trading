#!/usr/bin/env python3
"""Проверка Bybit API ключей и получение баланса для Telegram"""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, '/Users/anatolij/.openclaw/workspace/crypto-drl-bot/src')

from src.bybit_integration import BybitDataFetcher
from src.telegram_reporter import TelegramReporter

# Загрузка .env
load_dotenv()

# Инициализация Bybit API с тестовой сетью
fetcher = BybitDataFetcher(
    api_key=os.getenv('BYBIT_API_KEY'),
    api_secret=os.getenv('BYBIT_API_SECRET'),
    testnet=True
)

print("=== Проверка Bybit API ===")
# Попробуйте получить данные клина
df = fetcher.get_recent_candles('BTCUSDT', '1h', days=1)
if df is None or len(df) == 0:
    print("❌ Failed to fetch data")
else:
    latest = df.iloc[-1]
    print(f'✅ Bybit подключён. Последний кендл:')
    print(f'   Time: {latest.name}')
    print(f'   Close: ${new['close']:.2f}')

print()
print("=== Проверка баланса ===")
# Для баланса нужно использовать приватный API
# В файле bybit_integration.py приватных методов нет
# Давайте добавим метод для получения баланса
# Нужно отправить запрос с подписью по подписи HMAC-SHA256
import hmac
import hashlib
import json

base_url = 'https://api-testnet.bybit.com'

# Функция для подписи запроса

def make_private_request(endpoint, params):
    # Подписанный запрос к Bybit
    params['api_key'] = fetcher.api_key
    params['timestamp'] = int(time.time() * 1000)
    
    # Создание сигнатура
    param_str = ''.join(f'{k}={v}' for k, v in sorted(params.items()))
    signature = hmac.new(
        fetcher.api_secret.encode(),
        param_str.encode(),
        hashlib.sha256
    ).hexdigest()
    
    params['signature'] = signature
    
    url = f'{base_url}{endpoint}'
    response = requests.get(url, params=params, timeout=15)
    return response

# Попробуйте получить баланс positions (позиций)
# в Bybit API путевой путь /v2/private/position/list
# Мы здесь просто запрашиваем баланса - используйте тестовый запрос

print("❌ Balance check not implemented - requires Bybit private API")

print()
print("=== Проверка Telegram ===")
try:
    reporter = TelegramReporter.from_environment()
    if reporter.test_connection():
        print('✅ Telegram подключён!')
    else:
        print('❌ Telegram не подключился')
except Exception as e:
    print(f'❌ Ошибка Telegram: {e}')