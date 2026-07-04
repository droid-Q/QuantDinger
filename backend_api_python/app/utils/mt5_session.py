"""Shared MT5 broker session registry."""

from app.utils.broker_session import BrokerSessionRegistry


mt5_sessions = BrokerSessionRegistry("mt5")


__all__ = ["mt5_sessions"]
