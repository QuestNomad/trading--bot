from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.routers.auth import get_current_user
from app.models.models import Trade

router = APIRouter()

@router.get("/")
def list_trades(status: str = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Trade).order_by(Trade.opened_at.desc())
    if status:
        q = q.filter(Trade.status == status)
    return q.limit(200).all()

@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db), user=Depends(get_current_user)):
    open_trades = db.query(Trade).filter(Trade.status == "offen").all()
    total_invested = sum(t.entry_price * (t.position_size or 0) for t in open_trades)
    return {
        "open_positions": len(open_trades),
        "total_invested": round(total_invested, 2),
        "trades": open_trades,
    }
