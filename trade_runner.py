#!/usr/bin/env python3
"""
Trade Runner — тестовый прогон стратегии на исторических данных Bybit.
Оценивает винрейт и отдаёт сводку в Telegram. Работает в цикле (несколько часов).
"""
import os
import sys
import time
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from bybit_integration import BybitDataFetcher
from technical_indicators import TechnicalIndicators
from trading_env import CryptoTradingEnv
from telegram_reporter import TelegramConfig

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("runner")

SYMBOL = "BTCUSDT"
INTERVAL = "5"          # 5-минутные свечи
LOOKBACK = 100
INITIAL_BALANCE = 1000.0
FEE = 0.001


class TradeStats:
    def __init__(self, initial=INITIAL_BALANCE):
        self.initial = initial
        self.balance = initial
        self.position = 0.0          # сколько монет держим
        self.avg_price = 0.0
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.rounds = 0
        self.rounds_run = 0
        self.last_close = None      # последняя цена для mark-to-market открытой позиции

    def win_rate(self):
        closed = self.wins + self.losses
        return (self.wins / closed * 100) if closed else 0.0

    def total_value(self, current_close=None):
        """Mark-to-market: наличные + стоимость открытой позиции по текущей цене."""
        close = current_close if current_close is not None else self.last_close
        if self.position > 0 and close is not None:
            return self.balance + self.position * close
        return self.balance

    def summary(self, current_close=None):
        value = self.total_value(current_close)
        return {
            "rounds_run": self.rounds_run,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate(),
            "balance": self.balance,
            "position": self.position,
            "value": value,
            "pnl": value - self.initial,
            "pnl_pct": (value - self.initial) / self.initial * 100 if self.initial else 0,
        }


def run_one_round(fetcher, ti, stats, days=30, max_trades=50):
    """Один прогон на исторических данных."""
    df = fetcher.get_recent_candles(SYMBOL, INTERVAL, days=days)
    if df is None or len(df) < LOOKBACK + 50:
        logger.warning("Недостаточно данных, пропускаем раунд")
        return

    df = ti.add_technical_indicators(df)

    rows = df.to_dict('records')
    # торгуем по индикаторам
    for i in range(LOOKBACK, len(rows)):
        r = rows[i]
        close = float(r['close'])
        rsi = float(r['rsi']) if r['rsi'] is not None else 50
        atr = float(r['atr']) if r['atr'] is not None else 0

        # --- тестовая логика (замена RL-агента) ---
        entry_price = stats.avg_price

        if stats.position == 0 and rsi < 35:
            # buy
            qty = (stats.balance * 0.95) / close
            stats.position = qty
            stats.avg_price = close
            stats.balance = 0.0
            stats.trades += 1

        elif stats.position > 0:
            # TP / SL по ATR
            tp = entry_price * 1.0025   # +0.25%
            sl = entry_price * 0.9975   # -0.25%
            if rsi > 65 or close >= tp or close <= sl:
                proceeds = stats.position * close * (1 - FEE)
                pnl = proceeds - (stats.position * entry_price)
                stats.balance = proceeds
                if pnl > 0:
                    stats.wins += 1
                else:
                    stats.losses += 1
                stats.total_pnl += pnl
                stats.position = 0.0
                stats.avg_price = 0.0
        # --- конец логики ---

        if stats.trades >= max_trades:
            break

    stats.rounds_run += 1
    # mark-to-market на последней цене раунда
    last_close = rows[-1]['close'] if rows else None
    stats.last_close = last_close
    s = stats.summary(last_close)
    logger.info(f"Раунд завершён: стоимость=${s['value']:.2f} (баланс={s['balance']:.2f}), "
                f"сделок={s['trades']}, винрейт={s['win_rate']:.1f}%, PnL={s['pnl']:.2f}$")


def main():
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    os.environ.update({k: v for k, v in env.items() if v})

    # Ключи Bybit из .env (TESTNET по умолчанию false)
    testnet = os.environ.get('TESTNET', 'false').strip().lower() == 'true'

    fetcher = BybitDataFetcher(testnet=testnet)
    ti = TechnicalIndicators()

    reporter = None
    try:
        reporter = TelegramConfig.from_environment()
    except Exception as e:
        logger.warning(f"Telegram недоступен: {e}")

    stats = TradeStats()

    # Сколько часов крутим прогоны
    hours = int(os.environ.get('RUN_HOURS', '4'))
    deadline = time.time() + hours * 3600
    round_no = 0

    if reporter:
        reporter.send_risk_alert("RUN_START",
                                 f"🚀 Тестовый прогон бота запущен ({SYMBOL}, {INTERVAL}). "
                                 f"Длительность ~{hours} ч. Ключ на {'testnet' if testnet else 'mainnet'}.",
                                 "INFO")

    while time.time() < deadline:
        round_no += 1
        logger.info(f"=== Раунд {round_no} ===")
        try:
            run_one_round(fetcher, ti, stats)
        except Exception as e:
            logger.error(f"Ошибка раунда: {e}")

        s = stats.summary()
        logger.info(f"Промежуточный итог: {s}")

        # Отчёт каждые ~30 минут
        if reporter and round_no % 3 == 0 or round_no == 1:
            reporter.send_report("portfolio_summary", {
                "portfolio_value": s["value"],
                "cash_balance": s["balance"],
                "crypto_held": s["position"],
                "total_return": s["pnl"],
                "total_return_percent": s["pnl_pct"],
                "total_trades": s["trades"],
                "winning_trades": s["wins"],
                "losing_trades": s["losses"],
            })
            reporter.send_report("trading_stats", {
                "total_trades": s["trades"],
                "win_rate": s["win_rate"],
                "avg_win": 0, "avg_loss": 0,
                "max_drawdown": 0, "sharpe_ratio": 0,
                "profit_factor": 0,
                "current_streak": 0, "max_streak": 0,
            })
            logger.info("Отчёт отправлен в Telegram")

        time.sleep(60)  # пауза между раундами

    # Финальный подробный отчёт
    s = stats.summary()
    logger.info(f"=== ФИНАЛ: {s} ===")
    if reporter:
        report = (f"📊 **ИТОГОВЫЙ ОТЧЁТ ТЕСТОВОГО ПРОГОНА**\n\n"
                  f"📈 Раундов: {s['rounds_run']}\n"
                  f"🔄 Сделок: {s['trades']} (выигрыш: {s['wins']}, проигрыш: {s['losses']})\n"
                  f"🎯 **Винрейт: {s['win_rate']:.1f}%**\n"
                  f"💰 Стоимость портфеля: ${s['value']:.2f}\n"
                  f"📊 PnL: ${s['pnl']:.2f} ({s['pnl_pct']:+.2f}%)\n\n"
                  f"Цикл завершён. Бот останавливается.")
        reporter.send_risk_alert("RUN_END", report, "INFO")


if __name__ == "__main__":
    main()