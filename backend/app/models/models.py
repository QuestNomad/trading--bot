from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False, unique=True)
    asset_type = Column(String(20))  # aktie, crypto, etf
    ticker_id = Column(String(50))   # yfinance/coingecko ID
    sector = Column(String(50))
    is_short = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"))
    signal = Column(String(20))       # KAUFEN, VERKAUFEN
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    score = Column(Integer)
    rsi = Column(Float)
    sma20 = Column(Float)
    stop_loss = Column(Float)
    trailing_stop = Column(Float)
    position_size = Column(Float)
    status = Column(String(20), default="offen")  # offen, geschlossen, archiviert
    result_pct = Column(Float, nullable=True)
    broker = Column(String(20))       # alpaca, t212, paper
    broker_order_id = Column(String(100), nullable=True)
    opened_at = Column(DateTime, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)

class ScanResult(Base):
    __tablename__ = "scan_results"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"))
    signal = Column(String(20))
    score = Column(Integer)
    price = Column(Float)
    rsi = Column(Float)
    sma20 = Column(Float)
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    atr = Column(Float)
    trailing_stop = Column(Float)
    sentiment_world = Column(Float, nullable=True)
    sentiment_eu = Column(Float, nullable=True)
    scanned_at = Column(DateTime, server_default=func.now())

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
