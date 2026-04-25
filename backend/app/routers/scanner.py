from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.routers.auth import get_current_user
from app.models.models import Asset, ScanResult

router = APIRouter()

@router.get("/assets")
def list_assets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(Asset).filter(Asset.is_active == True).all()

@router.get("/latest")
def latest_scan(db: Session = Depends(get_db), user=Depends(get_current_user)):
    results = db.query(ScanResult).order_by(ScanResult.scanned_at.desc()).limit(100).all()
    return results

@router.post("/run")
def trigger_scan(user=Depends(get_current_user)):
    # TODO: Trigger Celery task for scan
    return {"message": "Scan triggered", "status": "queued"}
