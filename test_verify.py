#!/usr/bin/env python3
"""Quick verification script"""
import sys
sys.path.insert(0, '/Users/anatolij/.openclaw/workspace/crypto-drl-bot-venv/lib/python3.14/site-packages')

from src.bybit_integration import BybitDataFetcher
from src.telegram_reporter import TelegramConfig

print("=== Проверка Bybit API ===")
fetcher = BybitDataFetcher(api_key='***', api_secret='***', testnet=True)
# Use kline history to get latest candle (more reliable than ticker/price)
df = fetcher.get_recent_candles(symbol='BTCUSDT', interval='1h', days=1)
if df is None:
    print("❌ Failed to fetch data")
else:
    if len(df) > 0:
        latest = df.iloc[-1]
        print(f"✅ Bybit подключён. Последний кендл для BTCUSDT ({latest['interval']}):")
        print(f"   Last timestamp: {latest['timestamp']}")
        print(f"   Close price: ${latest['close']:.2f}")
        print(f"   Open: ${latest['open']:.2f}, High: ${latest['high']:.2f}, Low: ${latest['low']:.2f}")

print()
print("=== Проверка Telegram ===")
try:
    reporter = TelegramConfig.from_environment()
    if reporter.test_connection():
        print("✅ Telegram подключён и тестовое сообщение отправлено!")
    else:
        print("❌ Telegram не подключился")
except Exception as e:
    print(f"❌ Ошибка Telegram: {e}")