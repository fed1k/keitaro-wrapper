from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.config import Settings, get_settings
from app.countries import COUNTRIES
from app.db import get_db
from app.keitaro import KeitaroClient, KeitaroError, get_keitaro
from app.models import Campaign, OfferEvent
from app.schemas import CampaignCreate, CampaignOut, Interval, OfferAdd, OfferOption, SharesUpdate

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Keitaro wrapper", version="1.0.0")


@app.exception_handler(KeitaroError)
def keitaro_error(_: Request, exc: KeitaroError):
    status = exc.status if exc.status in (400, 404, 409, 422) else 502
    return JSONResponse(status_code=status, content={"detail": f"Keitaro: {exc.detail}"})


@app.exception_handler(services.ServiceError)
def service_error(_: Request, exc: services.ServiceError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
@app.get("/api/meta")
def meta(cfg: Settings = Depends(get_settings)):
    return {
        "prefix": cfg.campaign_prefix,
        "domain_id": cfg.keitaro_domain_id,
        "group_id": cfg.keitaro_group_id,
        "traffic_source_id": cfg.keitaro_traffic_source_id,
        "countries": [{"code": c, "name": n} for c, n in COUNTRIES.items()],
    }


@app.get("/api/offers", response_model=list[OfferOption])
def offers(q: str = "", limit: int = Query(20, le=100), kt: KeitaroClient = Depends(get_keitaro)):
    q = q.strip().lower()
    items = [o for o in kt.list_offers() if o.get("state") != "deleted"]
    if q:
        items = [o for o in items if q in o["name"].lower() or q == str(o["id"])]
    return [OfferOption(id=o["id"], name=o["name"], state=o.get("state", "")) for o in items[:limit]]


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------
@app.post("/api/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(
    data: CampaignCreate,
    db: Session = Depends(get_db),
    kt: KeitaroClient = Depends(get_keitaro),
    cfg: Settings = Depends(get_settings),
):
    return services.create_campaign(db, kt, cfg, data)


@app.get("/api/campaigns")
def list_campaigns(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    q: str = "",
    db: Session = Depends(get_db),
    kt: KeitaroClient = Depends(get_keitaro),
    cfg: Settings = Depends(get_settings),
):
    """`mine` — campaigns with our prefix; `all` — every campaign the API key can see."""
    local = {c.keitaro_id for c in db.scalars(select(Campaign))}
    items = kt.list_campaigns()
    if scope == "mine":
        items = [c for c in items if c["id"] in local or c["name"].startswith(cfg.campaign_prefix)]
    if q.strip():
        ql = q.strip().lower()
        items = [c for c in items if ql in c["name"].lower() or ql == str(c["id"])]
    return [
        {"id": c["id"], "name": c["name"], "alias": c.get("alias"), "group": c.get("group"),
         "state": c.get("state"), "created_here": c["id"] in local}
        for c in sorted(items, key=lambda c: c["id"], reverse=True)
    ]


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: int,
    interval: Interval = "all_time",
    kt: KeitaroClient = Depends(get_keitaro),
    cfg: Settings = Depends(get_settings),
):
    return services.campaign_view(kt, cfg, campaign_id, interval)


@app.post("/api/campaigns/{campaign_id}/streams/{stream_id}/offers")
def add_offer(campaign_id: int, stream_id: int, body: OfferAdd,
              db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    services.add_offer(db, kt, campaign_id, stream_id, body.offer_id)
    return {"ok": True}


@app.delete("/api/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}")
def remove_offer(campaign_id: int, stream_id: int, offer_id: int,
                 db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    services.remove_offer(db, kt, campaign_id, stream_id, offer_id)
    return {"ok": True}


@app.put("/api/campaigns/{campaign_id}/streams/{stream_id}/shares")
def update_shares(campaign_id: int, stream_id: int, body: SharesUpdate,
                  db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    services.set_shares(db, kt, campaign_id, stream_id, body.shares)
    return {"ok": True}


@app.get("/api/campaigns/{campaign_id}/events")
def campaign_events(campaign_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(OfferEvent).where(OfferEvent.keitaro_campaign_id == campaign_id)
        .order_by(OfferEvent.id.desc()).limit(50)
    )
    return [
        {"id": e.id, "stream_id": e.stream_id, "action": e.action, "offer_id": e.offer_id,
         "shares_after": e.shares_after, "created_at": e.created_at.isoformat()}
        for e in rows
    ]


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/campaigns/{campaign_id}", include_in_schema=False)
def editor_page(campaign_id: int):
    if campaign_id <= 0:
        raise HTTPException(404)
    return FileResponse(STATIC / "index.html")
