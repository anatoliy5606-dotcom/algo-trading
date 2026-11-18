"""
Crypto Trading DRL Bot - Main Entry Point
Integrates Bybit API, Telegram reporting, and PPO RL agent.
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from bybit_integration import BybitDataFetcher
from telegram_reporter import TelegramReporter, TelegramConfig
from trading_env import CryptoTradingEnv
from neural_networks import PPOAgent
from technical_indicators import TechnicalIndicators

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/Users/anatolij/.openclaw/workspace/crypto-drl-bot/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CryptoTradingBot:
    """
    Main trading bot class that orchestrates data fetching,
    RL agent execution, and Telegram reporting.
    """

    def __init__(self, config: dict):
        """
        Initialize the trading bot.

        Args:
            config (dict): Configuration dictionary with API keys and settings
        """
        self.config = config
        self.symbol = config.get('symbol', 'BTCUSDT')
        self.interval = config.get('interval', '1h')
        self.initial_balance = config.get('initial_balance', 1000)
        self.lookback_window = config.get('lookback_window', 100)
        self.transaction_fee = config.get('transaction_fee', 0.001)
        self.testnet = config.get('testnet', True)

        # Initialize components
        self.data_fetcher = None
        self.telegram_reporter = None
        self.rl_agent = None
        self.trading_env = None
        self.ti = TechnicalIndicators()

        # Trading state
        self.current_step = 0
        self.balance = self.initial_balance
        self.crypto_held = 0
        self.net_worth = self.initial_balance
        self.prev_net_worth = self.initial_balance
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.peak_net_worth = self.initial_balance

        logger.info(f"Trading bot initialized for {self.symbol} on {'Testnet' if self.testnet else 'Mainnet'}")

    def initialize(self):
        """Initialize all components"""
        logger.info("Initializing components...")

        # Initialize Bybit data fetcher (keys auto-loaded from .env)
        self.data_fetcher = BybitDataFetcher(testnet=self.testnet)
        logger.info("Bybit data fetcher initialized")

        # Initialize Telegram reporter
        try:
            self.telegram_reporter = TelegramConfig.from_environment()
            if self.telegram_reporter.test_connection():
                logger.info("Telegram reporter initialized and connected")
            else:
                logger.warning("Telegram reporter initialized but connection test failed")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram reporter: {e}")
            self.telegram_reporter = None

        # Initialize RL agent
        self.rl_agent = PPOAgent(
            input_shape=(self.lookback_window, 4),
            action_dim=3,  # Buy, Hold, Sell
            device='cpu'
        )
        logger.info("RL agent initialized")

        # Send startup notification
        if self.telegram_reporter:
            self.telegram_reporter.send_risk_alert(
                alert_type="BOT_STARTED",
                message=f"Trading bot initialized for {self.symbol}\n"
                        f"Initial balance: ${self.initial_balance}\n"
                        f"Testnet: {'Yes' if self.testnet else 'No'}\n"
                        f"Strategy: PPO RL with CNN-LSTM",
                severity="INFO"
            )

    def fetch_historical_data(self, days: int = 30):
        """
        Fetch historical data for training.

        Args:
            days (int): Number of days of historical data

        Returns:
            pd.DataFrame: DataFrame with historical data and indicators
        """
        logger.info(f"Fetching {days} days of historical data...")

        # Fetch data from Bybit
        df = self.data_fetcher.get_recent_candles(
            symbol=self.symbol,
            interval=self.interval,
            days=days
        )

        if df is None or df.empty:
            logger.error("Failed to fetch historical data")
            return None

        # Add technical indicators
        df = self.ti.add_technical_indicators(df)
        logger.info(f"Historical data prepared: {len(df)} data points")

        return df

    def prepare_trading_environment(self, df):
        """
        Prepare the trading environment with data.

        Args:
            df (pd.DataFrame): DataFrame with historical data and indicators
        """
        logger.info("Preparing trading environment...")

        self.trading_env = CryptoTradingEnv(
            df=df,
            initial_balance=self.initial_balance,
            lookback_window=self.lookback_window
        )
        logger.info("Trading environment prepared")

    def get_market_update(self, current_price: float, prev_price: float):
        """
        Get market update data for Telegram report.

        Args:
            current_price (float): Current market price
            prev_price (float): Previous market price

        Returns:
            dict: Market update data
        """
        price_change = current_price - prev_price
        price_change_percent = (price_change / prev_price) * 100 if prev_price > 0 else 0

        # Get latest indicators
        latest_data = self.trading_env.df.iloc[self.trading_env.current_step]
        rsi = latest_data.get('rsi', 0)
        atr = latest_data.get('atr', 0)
        volume = latest_data.get('volume_from', 0)

        return {
            'symbol': self.symbol,
            'current_price': current_price,
            'price_change': price_change,
            'price_change_percent': price_change_percent,
            'volume': volume,
            'rsi': rsi,
            'atr': atr,
        }

    def execute_trade(self, action: int, price: float):
        """
        Execute a trade based on RL agent's action.

        Args:
            action (int): Action (0=Hold, 1=Buy, 2=Sell)
            price (float): Current market price
        """
        action_names = {0: 'HOLD', 1: 'BUY', 2: 'SELL'}
        action_name = action_names.get(action, 'UNKNOWN')

        if action == 1:  # Buy
            if self.balance > 0:
                # Calculate position size (use 95% of balance to leave room for fees)
                crypto_to_buy = (self.balance * 0.95) / price
                crypto_to_buy *= (1 - self.transaction_fee)

                self.crypto_held += crypto_to_buy
                self.balance = 0
                self.total_trades += 1

                logger.info(f"BUY: {crypto_to_buy:.6f} {self.symbol} at ${price:.2f}")

                # Send Telegram notification
                if self.telegram_reporter:
                    self.telegram_reporter.send_trade_execution(
                        action='BUY',
                        symbol=self.symbol,
                        price=price,
                        quantity=crypto_to_buy,
                        pnl=0,
                        pnl_percent=0
                    )

        elif action == 2:  # Sell
            if self.crypto_held > 0:
                cash_to_receive = self.crypto_held * price
                cash_to_receive *= (1 - self.transaction_fee)

                # Calculate P&L
                pnl = cash_to_receive - (self.crypto_held * price * (1 + self.transaction_fee))
                pnl_percent = (pnl / (self.crypto_held * price)) * 100 if self.crypto_held > 0 else 0

                # Update stats
                self.balance += cash_to_receive
                self.total_pnl += pnl
                self.total_trades += 1

                if pnl > 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1

                logger.info(f"SELL: {self.crypto_held:.6f} {self.symbol} at ${price:.2f} | P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)")

                # Send Telegram notification
                if self.telegram_reporter:
                    self.telegram_reporter.send_trade_execution(
                        action='SELL',
                        symbol=self.symbol,
                        price=price,
                        quantity=self.crypto_held,
                        pnl=pnl,
                        pnl_percent=pnl_percent
                    )

                self.crypto_held = 0

    def update_portfolio(self, current_price: float):
        """
        Update portfolio values.

        Args:
            current_price (float): Current market price
        """
        self.prev_net_worth = self.net_worth
        self.net_worth = self.balance + (self.crypto_held * current_price)

        # Update peak and drawdown
        if self.net_worth > self.peak_net_worth:
            self.peak_net_worth = self.net_worth

        drawdown = self.peak_net_worth - self.net_worth
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def send_periodic_report(self):
        """Send periodic portfolio summary and stats to Telegram"""
        if not self.telegram_reporter:
            return

        # Send portfolio summary
        total_return = self.net_worth - self.initial_balance
        total_return_percent = (total_return / self.initial_balance) * 100

        self.telegram_reporter.send_portfolio_summary(
            portfolio_value=self.net_worth,
            cash_balance=self.balance,
            crypto_held=self.crypto_held,
            total_return=total_return,
            total_return_percent=total_return_percent,
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades
        )

        # Send trading stats
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        avg_win = 0
        avg_loss = 0
        profit_factor = 0
        sharpe_ratio = 0
        current_streak = 0
        max_streak = 0

        self.telegram_reporter.send_trading_stats(
            total_trades=self.total_trades,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_drawdown=self.max_drawdown,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            current_streak=current_streak,
            max_streak=max_streak
        )

    def run(self, max_steps: int = 1000, report_interval: int = 100):
        """
        Run the trading bot.

        Args:
            max_steps (int): Maximum number of trading steps
            report_interval (int): Interval for sending Telegram reports
        """
        logger.info(f"Starting trading bot with max {max_steps} steps...")

        # Fetch historical data
        df = self.fetch_historical_data(days=30)
        if df is None:
            logger.error("Failed to start: no historical data")
            return

        # Prepare trading environment
        self.prepare_trading_environment(df)

        # Reset environment (Gymnasium: reset returns (obs, info))
        state, _ = self.trading_env.reset()
        self.prev_net_worth = self.initial_balance

        # Trading loop
        for step in range(max_steps):
            self.current_step = step + 1

            # Get current price
            current_price = self.trading_env.df.iloc[self.trading_env.current_step]['close']
            prev_price = self.trading_env.df.iloc[self.trading_env.current_step - 1]['close']

            # Get action from RL agent
            action, _, _ = self.rl_agent.get_action(state, deterministic=False)

            # Execute trade
            self.execute_trade(action, current_price)

            # Update portfolio
            self.update_portfolio(current_price)

            # Step the environment (Gymnasium: obs, reward, terminated, truncated, info)
            state, reward, done, truncated, info = self.trading_env.step(action)
            if truncated:
                done = True

            # Send periodic reports
            if step % report_interval == 0:
                # Send market update
                market_data = self.get_market_update(current_price, prev_price)
                if self.telegram_reporter:
                    self.telegram_reporter.send_market_update(**market_data)

                # Send portfolio summary
                self.send_periodic_report()

                logger.info(f"Step {step}/{max_steps} | Net Worth: ${self.net_worth:.2f} | "
                           f"Balance: ${self.balance:.2f} | Crypto: {self.crypto_held:.6f}")

            if done:
                logger.info("Trading environment reached end of data")
                break

        # Send final report
        if self.telegram_reporter:
            self.send_periodic_report()
            self.telegram_reporter.send_risk_alert(
                alert_type="BOT_STOPPED",
                message=f"Trading bot stopped after {self.current_step} steps\n"
                        f"Final net worth: ${self.net_worth:.2f}\n"
                        f"Total return: ${self.net_worth - self.initial_balance:.2f} "
                        f"({((self.net_worth - self.initial_balance) / self.initial_balance) * 100:.2f}%)",
                severity="INFO"
            )

        logger.info(f"Trading bot finished. Final net worth: ${self.net_worth:.2f}")


def load_config():
    """
    Load configuration from environment variables.

    Returns:
        dict: Configuration dictionary
    """
    from dotenv import load_dotenv
    load_dotenv('/Users/anatolij/.openclaw/workspace/crypto-drl-bot/.env')

    config = {
        'symbol': os.getenv('SYMBOL', 'BTCUSDT'),
        'interval': os.getenv('INTERVAL', '1h'),
        'initial_balance': float(os.getenv('INITIAL_BALANCE', 1000)),
        'lookback_window': int(os.getenv('LOOKBACK_WINDOW', 100)),
        'transaction_fee': float(os.getenv('TRANSACTION_FEE', 0.001)),
        'testnet': os.getenv('TESTNET', 'true').lower() == 'true',
        'bybit_api_key': os.getenv('BYBIT_API_KEY'),
        'bybit_api_secret': os.getenv('BYBIT_API_SECRET'),
    }

    return config


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Crypto Trading DRL Bot - Starting")
    logger.info("=" * 60)

    # Load configuration
    config = load_config()

    # Validate configuration
    if not config['bybit_api_key'] or not config['bybit_api_secret']:
        logger.error("Bybit API keys not found. Please set BYBIT_API_KEY and BYBIT_API_SECRET in .env file")
        sys.exit(1)

    # Initialize and run bot
    bot = CryptoTradingBot(config)
    bot.initialize()

    # Run for 1000 steps (adjust as needed)
    bot.run(max_steps=1000, report_interval=100)


if __name__ == "__main__":
    main()
