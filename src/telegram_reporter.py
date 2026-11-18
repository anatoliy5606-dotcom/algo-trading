"""
Telegram Reporter Module for Crypto Trading DRL Bot.
Sends trading updates, statistics, and alerts to Telegram channels
via synchronous HTTP requests (no asyncio / event-loop issues).
"""

import logging
import time
import json
import requests
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"


@dataclass
class TradingReport:
    """Data class for trading report"""
    timestamp: datetime
    message: str
    parse_mode: str = "Markdown"
    reply_markup: Optional[dict] = None


class TelegramReporter:
    """
    Handles sending trading updates to Telegram channels/groups.
    Uses synchronous requests to the Telegram Bot HTTP API.
    """

    def __init__(self, bot_token: str, chat_id: str, parse_mode: str = "Markdown"):
        """
        Initialize the Telegram reporter.

        Args:
            bot_token (str): Telegram bot token
            chat_id (str): Telegram chat/group ID (e.g., channel username or numeric ID)
            parse_mode (str): Parse mode for messages ('Markdown' or 'HTML')
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.last_message_id = None
        self.setup_successful = False

        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 1.0

    def _call(self, method: str, payload: dict) -> Optional[dict]:
        """
        Perform a synchronous request to the Telegram Bot API.

        Args:
            method (str): Telegram API method (e.g., 'getMe', 'sendMessage')
            payload (dict): JSON payload for the request

        Returns:
            Optional[dict]: 'result' field from the response, or None on failure
        """
        url = API_URL.format(token=self.bot_token, method=method)
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                logger.error(f"Telegram {method} failed: {data.get('description')} "
                             f"(code={data.get('error_code')})")
                return None
            return data.get("result")
        except requests.RequestException as e:
            logger.error(f"Telegram {method} network error: {e}")
            return None
        except Exception as e:
            logger.error(f"Telegram {method} unexpected error: {e}")
            return None

    def __connect_to_telegram(self) -> bool:
        """
        Verify the bot token and chat by calling getMe + a ping message.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            result = self._call("getMe", {})
            if not result:
                return False

            username = result.get("username")
            logger.info(f"Connected to Telegram bot: @{username}")
            self.setup_successful = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Telegram: {e}")
            return False

    def _send_message_with_retry(self, report: TradingReport) -> bool:
        """
        Send message to Telegram with retry logic (synchronous).

        Args:
            report (TradingReport): Trading report to send

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self.setup_successful:
            if not self.__connect_to_telegram():
                return False

        for attempt in range(self.max_retries):
            payload = {
                "chat_id": self.chat_id,
                "text": report.message,
                "parse_mode": report.parse_mode,
            }
            result = self._call("sendMessage", payload)
            if result:
                self.last_message_id = result.get("message_id")
                logger.info(f"Message sent successfully (attempt {attempt + 1})")
                return True

            # If parse_mode fails (markdown formatting error), retry without it
            if report.parse_mode and attempt == 0:
                logger.warning("Retrying without parse_mode (markdown issue)")
                payload = {
                    "chat_id": self.chat_id,
                    "text": report.message,
                }
                result = self._call("sendMessage", payload)
                if result:
                    self.last_message_id = result.get("message_id")
                    logger.info("Message sent (no parse_mode)")
                    return True

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        logger.error(f"Failed to send message after {self.max_retries} attempts")
        return False

    def _format_report(self, report_type: str, data: dict) -> TradingReport:
        """
        Format trading data into a Telegram report.

        Args:
            report_type (str): Type of report
            data (dict): Trading data to format

        Returns:
            TradingReport: Formatted report
        """
        message = self._generate_message(report_type, data)
        return TradingReport(timestamp=datetime.now(), message=message, parse_mode=self.parse_mode)

    def send_report(self, report_type: str, data: dict) -> bool:
        """
        Send a formatted trading report to Telegram.

        Args:
            report_type (str): Type of report
            data (dict): Trading data

        Returns:
            bool: True if report sent successfully, False otherwise
        """
        try:
            report = self._format_report(report_type, data)
            ok = self._send_message_with_retry(report)
            if ok:
                logger.info(f"Successfully sent {report_type} report to Telegram")
            else:
                logger.error(f"Failed to send {report_type} report to Telegram")
            return ok
        except Exception as e:
            logger.error(f"Error preparing/sending report: {e}")
            return False

    def _generate_message(self, report_type: str, data: dict) -> str:
        """Generate a formatted message based on report type."""
        if report_type == "market_update":
            return self._format_market_update(data)
        elif report_type == "trade_executed":
            return self._format_trade_execution(data)
        elif report_type == "portfolio_summary":
            return self._format_portfolio_summary(data)
        elif report_type == "risk_alert":
            return self._format_risk_alert(data)
        elif report_type == "trading_stats":
            return self._format_trading_stats(data)
        else:
            return self._format_generic_report(report_type, data)

    def _format_market_update(self, data: dict) -> str:
        symbol = data.get('symbol', 'BTC/USDT')
        current_price = data.get('current_price', 0)
        price_change = data.get('price_change', 0)
        price_change_percent = data.get('price_change_percent', 0)
        volume = data.get('volume', 0)
        rsi = data.get('rsi', 0)
        atr = data.get('atr', 0)
        trend_emoji = "📈" if price_change > 0 else "📉"

        return (
            f"{trend_emoji} **MARKET UPDATE - {symbol}**\n\n"
            f"💰 **Price:** ${current_price:,.2f}\n"
            f"📊 **Change:** {price_change:,.2f} ({price_change_percent:+.2f}%)\n"
            f"🔄 **Volume:** {volume:,.0f}\n"
            f"📈 **RSI:** {rsi:.2f}\n"
            f"📊 **ATR:** {atr:.2f}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_trade_execution(self, data: dict) -> str:
        action = data.get('action', 'UNKNOWN')
        symbol = data.get('symbol', 'BTC/USDT')
        price = data.get('price', 0)
        quantity = data.get('quantity', 0)
        pnl = data.get('pnl', 0)
        pnl_percent = data.get('pnl_percent', 0)
        action_emoji = "🟢" if action.upper() == 'BUY' else "🔴"

        return (
            f"{action_emoji} **TRADE EXECUTED**\n\n"
            f"📍 **Symbol:** {symbol}\n"
            f"{action_emoji} **Action:** {action}\n"
            f"💰 **Price:** ${price:,.2f}\n"
            f"📦 **Quantity:** {quantity:.6f}\n"
            f"💵 **P&L:** ${pnl:,.2f} ({pnl_percent:+.2f}%)\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_portfolio_summary(self, data: dict) -> str:
        portfolio_value = data.get('portfolio_value', 0)
        cash_balance = data.get('cash_balance', 0)
        crypto_held = data.get('crypto_held', 0)
        total_return = data.get('total_return', 0)
        total_return_percent = data.get('total_return_percent', 0)
        total_trades = data.get('total_trades', 0)
        winning_trades = data.get('winning_trades', 0)
        losing_trades = data.get('losing_trades', 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        trend_emoji = "📈" if total_return > 0 else "📉"

        return (
            f"{trend_emoji} **PORTFOLIO SUMMARY**\n\n"
            f"💼 **Total Value:** ${portfolio_value:,.2f}\n"
            f"💰 **Cash:** ${cash_balance:,.2f}\n"
            f"🪙 **Crypto:** {crypto_held:.6f}\n\n"
            f"📊 **Performance:**\n"
            f"   📈 Total Return: ${total_return:,.2f} ({total_return_percent:+.2f}%)\n"
            f"   📊 Trades: {total_trades} (Wins: {winning_trades}, Losses: {losing_trades})\n"
            f"   🎯 Win Rate: {win_rate:.1f}%\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_risk_alert(self, data: dict) -> str:
        alert_type = data.get('alert_type', 'RISK')
        message = data.get('message', '')
        severity = data.get('severity', 'MEDIUM')
        emoji = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}.get(severity, "🟡")

        return (
            f"{emoji} **RISK ALERT - {alert_type}**\n\n"
            f"{message}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_trading_stats(self, data: dict) -> str:
        total_trades = data.get('total_trades', 0)
        win_rate = data.get('win_rate', 0)
        avg_win = data.get('avg_win', 0)
        avg_loss = data.get('avg_loss', 0)
        max_drawdown = data.get('max_drawdown', 0)
        sharpe_ratio = data.get('sharpe_ratio', 0)
        profit_factor = data.get('profit_factor', 0)
        current_streak = data.get('current_streak', 0)
        max_streak = data.get('max_streak', 0)
        streak_emoji = "📈" if current_streak > 0 else "📉"

        return (
            f"📊 **TRADING STATISTICS**\n\n"
            f"📈 **Activity:**\n"
            f"   📊 Total Trades: {total_trades}\n"
            f"   🎯 Win Rate: {win_rate:.1f}%\n"
            f"   📈 Current Streak: {current_streak} {streak_emoji}\n"
            f"   🏆 Max Streak: {max_streak}\n\n"
            f"💰 **Performance:**\n"
            f"   💵 Average Win: ${avg_win:.2f}\n"
            f"   💵 Average Loss: ${avg_loss:.2f}\n"
            f"   📈 Profit Factor: {profit_factor:.2f}\n"
            f"   📊 Sharpe Ratio: {sharpe_ratio:.2f}\n"
            f"   📉 Max Drawdown: ${max_drawdown:.2f}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _format_generic_report(self, report_type: str, data: dict) -> str:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return f"📋 **REPORT: {report_type.upper()}**\n\n{data}\n\n⏰ {ts}"

    # Convenience wrappers
    def send_market_update(self, symbol, current_price, price_change, price_change_percent,
                           volume=0, rsi=0, atr=0) -> bool:
        return self.send_report("market_update", {
            'symbol': symbol, 'current_price': current_price,
            'price_change': price_change, 'price_change_percent': price_change_percent,
            'volume': volume, 'rsi': rsi, 'atr': atr,
        })

    def send_trade_execution(self, action, symbol, price, quantity, pnl, pnl_percent) -> bool:
        return self.send_report("trade_executed", {
            'action': action, 'symbol': symbol, 'price': price,
            'quantity': quantity, 'pnl': pnl, 'pnl_percent': pnl_percent,
        })

    def send_portfolio_summary(self, portfolio_value, cash_balance, crypto_held,
                               total_return, total_return_percent, total_trades,
                               winning_trades, losing_trades) -> bool:
        return self.send_report("portfolio_summary", {
            'portfolio_value': portfolio_value, 'cash_balance': cash_balance,
            'crypto_held': crypto_held, 'total_return': total_return,
            'total_return_percent': total_return_percent, 'total_trades': total_trades,
            'winning_trades': winning_trades, 'losing_trades': losing_trades,
        })

    def send_risk_alert(self, alert_type, message, severity="MEDIUM") -> bool:
        return self.send_report("risk_alert", {
            'alert_type': alert_type, 'message': message, 'severity': severity,
        })

    def send_trading_stats(self, total_trades, win_rate, avg_win, avg_loss,
                           max_drawdown, sharpe_ratio, profit_factor,
                           current_streak, max_streak) -> bool:
        return self.send_report("trading_stats", {
            'total_trades': total_trades, 'win_rate': win_rate,
            'avg_win': avg_win, 'avg_loss': avg_loss, 'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio, 'profit_factor': profit_factor,
            'current_streak': current_streak, 'max_streak': max_streak,
        })

    def test_connection(self) -> bool:
        if self.setup_successful:
            return True
        return self.__connect_to_telegram()


class TelegramConfig:
    """Helper for building TelegramReporter from .env or config file."""

    @staticmethod
    def from_environment() -> "TelegramReporter":
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            # Fall back to reading the project .env file
            env = {}
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
            )
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            env[k.strip()] = v.strip()
                bot_token = env.get('TELEGRAM_BOT_TOKEN')
                chat_id = env.get('TELEGRAM_CHAT_ID')

        if not bot_token or not chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required "
                "(set in .env or environment)"
            )
        return TelegramReporter(bot_token, chat_id)