"""
Bybit API Integration Module (v5) for Crypto Trading DRL Bot.
Fetches cryptocurrency data from Bybit API v5 with HMAC signing.
"""

import time
import logging
import hmac
import hashlib
import os
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bybit API v5 endpoints
BYBIT_V5_BASE_URL = "https://api.bybit.com/v5"
BYBIT_V5_TESTNET_URL = "https://api-testnet.bybit.com/v5"

# Rate limiting
RATE_LIMIT_DELAY = 0.1  # seconds between requests


class BybitDataFetcher:
    """
    Fetches cryptocurrency data from Bybit API v5.
    Supports both public (historical kline, ticker) and private (wallet balance) endpoints with HMAC signing.
    """

    def __init__(self, api_key=None, api_secret=None, testnet=None):
        """
        Initialize the Bybit v5 data fetcher.

        Auto-loads credentials from the project .env file when not passed explicitly.

        Args:
            api_key (str): Bybit API key (optional for public data, required for private)
            api_secret (str): Bybit API secret (optional for public data, required for private)
            testnet (bool): If None, read from TESTNET in .env (default True).
        """
        # Auto-load from .env when not provided
        env = self._load_env()
        if api_key is None:
            api_key = env.get("BYBIT_API_KEY")
        if api_secret is None:
            api_secret = env.get("BYBIT_API_SECRET")
        if testnet is None:
            testnet = env.get("TESTNET", "true").strip().lower() == "true"

        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = bool(testnet)

        # Bybit v5 base URL
        if testnet:
            self.base_url = BYBIT_V5_TESTNET_URL
            logger.info("Initialized Bybit V5 Testnet fetcher")
        else:
            self.base_url = BYBIT_V5_BASE_URL
            logger.info("Initialized Bybit V5 Mainnet fetcher")

        self.has_keys = api_key is not None and api_secret is not None

    @staticmethod
    def _load_env() -> dict:
        """
        Load environment variables from the project .env file.

        Returns:
            dict: Environment variables as key-value pairs.
        """
        env = {}
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
            logger.info(f"Loaded env from {env_path}")
        except FileNotFoundError:
            logger.warning(f"No .env file at {env_path}; using defaults")
        except Exception as e:
            logger.warning(f"Error loading .env: {e}")
        return env

    def _sign(self, params: dict) -> str:
        """
        Create HMAC-SHA256 signature for Bybit v5 private requests.

        Args:
            params (dict): Query parameters to sign

        Returns:
            str: HMAC-SHA256 hex signature
        """
        # Sort parameters alphabetically and concatenate as key=value pairs
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _make_request(self, endpoint: str, params: dict = None, retry_count: int = 3,
                      private: bool = False) -> dict:
        """
        Make a request to Bybit API v5 with rate limiting, retry logic, and optional HMAC signing.

        Args:
            endpoint (str): API endpoint path (e.g., '/market/ticker', '/account/wallet/balance')
            params (dict): Query parameters
            retry_count (int): Number of retries on failure
            private (bool): If True, require API keys and add HMAC signature

        Returns:
            dict or None: JSON response from API or None on failure
        """
        if private and not self.has_keys:
            logger.error("API keys are required for private endpoints")
            return None

        url = f"{self.base_url}{endpoint}"
        params = params or {}

        if private:
            params["api_key"] = self.api_key
            params["timestamp"] = int(time.time() * 1000)
            params["sign"] = self._sign(params)

        for attempt in range(retry_count):
            try:
                time.sleep(RATE_LIMIT_DELAY)

                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()

                data = response.json()

                # Bybit v5 response format: {"retCode": 0, "retMsg": "OK", "result": {...}}
                if data.get("retCode") != 0:
                    logger.error(f"Bybit API error: {data.get('retMsg', 'Unknown error')}")
                    if attempt < retry_count - 1:
                        time.sleep(1)
                        continue
                    return None

                return data

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error (attempt {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)
                else:
                    return None

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return None

        return None

    def get_current_price(self, symbol: str = "BTCUSDT") -> float:
        """
        Get current ticker price from Bybit v5.

        Args:
            symbol (str): Trading pair (e.g., 'BTCUSDT', 'ETHUSDT')

        Returns:
            float: Current price, or None on failure
        """
        endpoint = "/market/tickers"
        params = {"category": "spot", "symbol": symbol}

        data = self._make_request(endpoint, params, private=False)

        if data and "result" in data:
            try:
                tickers = data["result"].get("list", [])
                if tickers:
                    price = float(tickers[0]["lastPrice"])
                    logger.info(f"Current {symbol} price: ${price:.2f}")
                    return price
            except (ValueError, IndexError, KeyError) as e:
                logger.error(f"Error parsing price: {e}")
                return None

        logger.warning(f"Could not get current price for {symbol}")
        return None

    def get_kline_history(self, symbol: str = "BTCUSDT", interval: str = "60", limit: int = 200,
                          start_time: int = None, end_time: int = None) -> pd.DataFrame:
        """
        Fetch historical k-line/candlestick data from Bybit v5.

        Args:
            symbol (str): Trading pair
            interval (str): Candlestick interval ('1', '3', '5', '15', '30', '60', '120', '240', 'D', 'W', 'M')
                          '60' = 1 hour
            limit (int): Number of candles (max 1000)
            start_time (int): Start timestamp in milliseconds
            end_time (int): End timestamp in milliseconds

        Returns:
            pd.DataFrame: DataFrame with OHLCV data, or None on failure
        """
        endpoint = "/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        if start_time:
            params["start"] = start_time
        if end_time:
            params["end"] = end_time

        data = self._make_request(endpoint, params, private=False)

        if data and "result" in data:
            try:
                result = data["result"]
                klines = result.get("list", [])

                if not klines:
                    logger.warning(f"No kline data returned for {symbol}")
                    return None

                df = pd.DataFrame(klines)

                # Bybit v5 returns columns: [start, open, high, low, close, volume, turnover]
                df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]

                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].astype(float)

                # Convert timestamp (milliseconds) to datetime
                df["timestamp"] = pd.to_datetime(df["timestamp"].astype(float), unit="ms")
                df.set_index("timestamp", inplace=True)

                # Sort by timestamp (oldest first)
                df = df.sort_index()

                logger.info(f"Fetched {len(df)} candles for {symbol} at {interval} interval")
                return df

            except Exception as e:
                logger.error(f"Error parsing kline data: {e}")
                return None

        else:
            logger.warning(f"No kline data returned for {symbol}")
            return None

    def get_recent_candles(self, symbol: str = "BTCUSDT", interval: str = "60", days: int = 30) -> pd.DataFrame:
        """
        Fetch recent candles for a given number of days.

        Args:
            symbol (str): Trading pair
            interval (str): Candlestick interval
            days (int): Number of days of data

        Returns:
            pd.DataFrame: DataFrame with historical data
        """
        candles_per_day = {'1': 1440, '3': 480, '5': 288, '15': 96, '30': 48, '60': 24,
                           '120': 12, '240': 6, 'D': 1, 'W': 1/7, 'M': 1/30}

        per_day = candles_per_day.get(interval, 24)

        all_data = []
        end_time = int(datetime.now().timestamp() * 1000)

        # Fetch in chunks of 1000 (max per request)
        candles_needed = int(days * per_day)
        fetched = 0

        while fetched < candles_needed:
            limit = min(1000, candles_needed - fetched)

            kline_data = self.get_kline_history(
                symbol=symbol,
                interval=interval,
                limit=limit,
                end_time=end_time,
                start_time=None
            )

            if kline_data is not None and not kline_data.empty:
                all_data.append(kline_data)
                fetched += len(kline_data)
                # Move end_time to just before the oldest fetched candle
                end_time = int(kline_data.index[0].timestamp() * 1000) - 1
                logger.info(f"Fetched {fetched} candles so far...")
            else:
                logger.warning(f"Failed to fetch chunk, stopping at {fetched} candles")
                break

            if fetched < candles_needed:
                time.sleep(0.5)

        if all_data:
            combined_df = pd.concat(all_data)
            combined_df = combined_df[~combined_df.index.duplicated(keep="first")]
            combined_df = combined_df.sort_index()

            logger.info(f"Successfully fetched {len(combined_df)} total data points for {days} days")
            return combined_df

        logger.error("Failed to fetch any data")
        return None

    def get_wallet_balance(self, coin: str = "USDT") -> dict:
        """
        Get wallet balance from Bybit v5 (private endpoint with HMAC signing).

        Args:
            coin (str): Coin symbol (e.g., 'USDT', 'BTC')

        Returns:
            dict: Balance information or None on failure
        """
        if not self.has_keys:
            logger.error("API keys required for wallet balance")
            return None

        endpoint = "/account/wallet-balance"
        params = {"accountType": "UNIFIED", "coin": coin}

        data = self._make_request(endpoint, params, private=True)

        if data and "result" in data:
            try:
                result = data["result"]
                balance_list = result.get("list", [])

                if not balance_list:
                    logger.warning(f"No balance data returned for {coin}")
                    return None

                # Find the coin in the list
                for account in balance_list:
                    coins = account.get("coin", [])
                    for c in coins:
                        if c.get("coin") == coin:
                            info = {
                                "coin": c.get("coin"),
                                "walletBalance": c.get("walletBalance"),
                                "totalAvailableBalance": c.get("totalAvailableBalance"),
                                "totalOrderLock": c.get("totalOrderLock"),
                                "totalPositionMM": c.get("totalPositionMM"),
                                "accountType": account.get("accountType"),
                            }
                            logger.info(f"Wallet balance for {coin}: {info['walletBalance']}")
                            return info

                logger.warning(f"Coin {coin} not found in balance list")
                return None

            except Exception as e:
                logger.error(f"Error parsing wallet balance: {e}")
                return None

        else:
            logger.warning(f"No wallet balance returned")
            return None

    def get_available_balance(self, coin: str = "USDT") -> float:
        """
        Get available trading balance for a coin.

        Args:
            coin (str): Coin symbol

        Returns:
            float: Available balance, or None on failure
        """
        balance = self.get_wallet_balance(coin)
        if balance:
            return float(balance.get("totalAvailableBalance", 0))
        return None


# Example usage
if __name__ == "__main__":
    # Initialize fetcher
    fetcher = BybitDataFetcher(testnet=True)

    # Get current price
    price = fetcher.get_current_price("BTCUSDT")
    if price:
        print(f"Current BTC/USDT price: ${price:.2f}")

    # Get recent candles
    btc_data = fetcher.get_recent_candles("BTCUSDT", "60", days=7)
    if btc_data is not None:
        print(f"\nData shape: {btc_data.shape}")
        print(btc_data.head())