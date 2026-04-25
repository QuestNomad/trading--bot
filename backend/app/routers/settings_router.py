from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.routers.auth import get_current_user
from app.models.models import Settings

router = APIRouter()

DEFAULT_SETTINGS = {
    "buy_threshold": "8",
    "sell_threshold": "3",
    "kelly_fraction": "0.0694",
    "max_exposure": "0.80",
    "max_per_sector": "4",
    "scan_interval": "daily",
    "atr_multiplier": "3.0",
    "bb_period": "20",
    "rsi_period": "14",
    "auto_trade": "false",
    "broker_default": "paper",
}

class SettingUpdate(BaseModel):
    key: str
    value: str

@router.get("/")
def get_settings(db: Session = Depends(get_db), user=Depends(get_current_user)):
    db_settings = {s.key: s.value for s in db.query(Settings).all()}
    merged = {**DEFAULT_SETTINGS, **db_settings}
    return merged

@router.put("/")
def update_setting(setting: SettingUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    existing = db.query(Settings).filter(Settings.key == setting.key).first()
    if existing:
        existing.value = setting.value
    else:
        db.add(Settings(key=setting.key, value=setting.value))
    db.commit()
    return {"key": setting.key, "value": setting.value}
