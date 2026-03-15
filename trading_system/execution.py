from __future__ import annotations

import json
import uuid
from datetime import datetime

import requests

from trading_system.models import FillEvent


PAPER_TRADING_URL = "https://paper-api.alpaca.markets"


class AlpacaBrokerClient(object):
    def __init__(self, api_key, api_secret, base_url=PAPER_TRADING_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type": "application/json",
        })

    def get_account(self):
        response = self.session.get(self.base_url + "/v2/account", timeout=20)
        response.raise_for_status()
        return response.json()

    def get_clock(self):
        response = self.session.get(self.base_url + "/v2/clock", timeout=20)
        response.raise_for_status()
        return response.json()

    def submit_order(self, symbol, qty, side, order_type="market", time_in_force="day", limit_price=None, stop_price=None):
        client_order_id = "codex-%s" % uuid.uuid4().hex[:18]
        payload = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
        }
        if limit_price is not None:
            payload["limit_price"] = limit_price
        if stop_price is not None:
            payload["stop_price"] = stop_price
        response = self.session.post(self.base_url + "/v2/orders", data=json.dumps(payload), timeout=20)
        response.raise_for_status()
        body = response.json()
        return body.get("id", client_order_id), body


class AlpacaExecutionEngine(object):
    def __init__(self, broker_client, broker_name="alpaca_paper", commission_per_share=0.0):
        self.broker_client = broker_client
        self.broker_name = broker_name
        self.commission_per_share = commission_per_share

    def execute(self, symbol, side, quantity, market_price, order_type="market", time_in_force="day", limit_price=None, stop_price=None):
        order_id, order_payload = self.broker_client.submit_order(
            symbol=symbol,
            qty=quantity,
            side=side.lower(),
            order_type=order_type,
            time_in_force=time_in_force,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        filled_avg_price = order_payload.get("filled_avg_price")
        fill_price = float(filled_avg_price) if filled_avg_price not in (None, "") else market_price
        commission = quantity * self.commission_per_share
        return FillEvent(
            order_id=order_id,
            symbol=symbol,
            side=side.upper(),
            timestamp=datetime.utcnow(),
            quantity=quantity,
            requested_price=market_price,
            fill_price=fill_price,
            commission=commission,
            slippage=abs(fill_price - market_price),
            provider=self.broker_name,
        )


class PaperExecutionEngine(object):
    def __init__(self, broker_name, dry_run=False, slippage_bps=1.0, commission_per_share=0.0):
        self.broker_name = broker_name
        self.dry_run = dry_run
        self.slippage_bps = slippage_bps
        self.commission_per_share = commission_per_share

    def execute(self, symbol, side, quantity, market_price):
        order_id = "paper-%s" % uuid.uuid4().hex[:18]
        slippage = market_price * (self.slippage_bps / 10000.0)
        if side.upper() == "BUY":
            fill_price = market_price + slippage
        else:
            fill_price = market_price - slippage
        commission = quantity * self.commission_per_share
        return FillEvent(
            order_id=order_id,
            symbol=symbol,
            side=side.upper(),
            timestamp=datetime.utcnow(),
            quantity=quantity,
            requested_price=market_price,
            fill_price=fill_price,
            commission=commission,
            slippage=abs(fill_price - market_price),
            provider=self.broker_name,
        )
