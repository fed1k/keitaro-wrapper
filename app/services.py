import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign, OfferEvent
from app.schemas import CampaignCreate
from app.shares import split_evenly, validate_shares


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def apply_prefix(name: str, prefix: str) -> str:
    return name if name.startswith(prefix) else prefix + name


# --------------------------------------------------------------------------
# Creator
# --------------------------------------------------------------------------
def create_campaign(db: Session, kt: KeitaroClient, cfg: Settings, data: CampaignCreate) -> Campaign:
    offers = {o["id"]: o for o in kt.list_offers()}
    if data.offer_id not in offers:
        raise ServiceError(404, f"Оффер {data.offer_id} не найден в Keitaro")

    name = apply_prefix(data.name, cfg.campaign_prefix)
    alias = secrets.token_hex(4)
    campaign = kt.create_campaign(
        {
            "name": name,
            "alias": alias,
            "type": "position",
            "state": "active",
            "domain_id": cfg.keitaro_domain_id,
            "group_id": cfg.keitaro_group_id,
            "traffic_source_id": cfg.keitaro_traffic_source_id,
            "cost_type": "CPC",
            "cost_auto": True,
        }
    )
    cid = campaign["id"]

    # If a stream fails, roll back the half-created campaign so nothing dangles.
    try:
        google = kt.create_stream(
            {
                "campaign_id": cid,
                "type": "regular",
                "name": f"Geo {', '.join(data.geo)} → Google",
                "position": 1,
                "state": "active",
                "schema": "redirect",
                "action_type": "http",
                "action_payload": cfg.google_url,
                "filters": [{"name": "country", "mode": "accept", "payload": data.geo}],
            }
        )
        offers_stream = kt.create_stream(
            {
                "campaign_id": cid,
                "type": "regular",
                "name": "Offers",
                "position": 2,
                "state": "active",
                "schema": "landings",
                "action_type": "http",
                "offer_selection": "before_click",
                "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
            }
        )
    except KeitaroError:
        try:
            kt.delete_campaign(cid)
        except KeitaroError:
            pass
        raise

    domain = campaign.get("domain") or kt.get_campaign(cid).get("domain") or ""
    row = Campaign(
        keitaro_id=cid,
        name=name,
        alias=campaign.get("alias", alias),
        url=f"{domain.rstrip('/')}/{campaign.get('alias', alias)}",
        geo=data.geo,
        initial_offer_id=data.offer_id,
        google_stream_id=google["id"],
        offers_stream_id=offers_stream["id"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------
# Editor
# --------------------------------------------------------------------------
def _offer_payload(shares: dict[int, int], states: dict[int, str]) -> list[dict]:
    return [
        {"offer_id": oid, "share": share, "state": states.get(oid, "active")}
        for oid, share in shares.items()
    ]


def _load_offers_stream(kt: KeitaroClient, campaign_id: int, stream_id: int) -> dict:
    stream = kt.get_stream(stream_id)
    if stream.get("campaign_id") != campaign_id:
        raise ServiceError(404, "Поток не принадлежит этой кампании")
    if stream.get("schema") != "landings":
        raise ServiceError(400, "В этом потоке нет офферов (схема не «Лендинги и офферы»)")
    return stream


def _save(db: Session, kt: KeitaroClient, campaign_id: int, stream: dict,
          shares: dict[int, int], action: str, offer_id: int | None) -> dict:
    states = {o["offer_id"]: o.get("state", "active") for o in stream.get("offers", [])}
    updated = kt.update_stream(stream["id"], {"offers": _offer_payload(shares, states)})
    local = db.scalar(select(Campaign).where(Campaign.keitaro_id == campaign_id))
    db.add(
        OfferEvent(
            campaign_id=local.id if local else None,
            keitaro_campaign_id=campaign_id,
            stream_id=stream["id"],
            action=action,
            offer_id=offer_id,
            shares_after={str(k): v for k, v in shares.items()},
        )
    )
    db.commit()
    return updated


def add_offer(db: Session, kt: KeitaroClient, campaign_id: int, stream_id: int, offer_id: int) -> dict:
    stream = _load_offers_stream(kt, campaign_id, stream_id)
    current = [o["offer_id"] for o in stream.get("offers", [])]
    if offer_id in current:
        raise ServiceError(409, f"Оффер {offer_id} уже есть в потоке")
    if offer_id not in {o["id"] for o in kt.list_offers()}:
        raise ServiceError(404, f"Оффер {offer_id} не найден в Keitaro")
    shares = split_evenly(current + [offer_id])
    return _save(db, kt, campaign_id, stream, shares, "add", offer_id)


def remove_offer(db: Session, kt: KeitaroClient, campaign_id: int, stream_id: int, offer_id: int) -> dict:
    stream = _load_offers_stream(kt, campaign_id, stream_id)
    current = [o["offer_id"] for o in stream.get("offers", [])]
    if offer_id not in current:
        raise ServiceError(404, f"Оффера {offer_id} нет в потоке")
    rest = [oid for oid in current if oid != offer_id]
    if not rest:
        raise ServiceError(400, "Нельзя удалить последний оффер: поток останется без цели")
    shares = split_evenly(rest)
    return _save(db, kt, campaign_id, stream, shares, "remove", offer_id)


def set_shares(db: Session, kt: KeitaroClient, campaign_id: int, stream_id: int, shares: dict[int, int]) -> dict:
    stream = _load_offers_stream(kt, campaign_id, stream_id)
    current = {o["offer_id"] for o in stream.get("offers", [])}
    if set(shares) != current:
        raise ServiceError(409, "Список офферов изменился, обновите страницу")
    try:
        validate_shares(shares)
    except ValueError as exc:
        raise ServiceError(400, str(exc)) from exc
    ordered = {o["offer_id"]: shares[o["offer_id"]] for o in stream["offers"]}
    return _save(db, kt, campaign_id, stream, ordered, "reweight", None)


# --------------------------------------------------------------------------
# Campaign view with stats
# --------------------------------------------------------------------------
MEASURES = ["clicks", "stream_unique_clicks", "bots", "conversions", "revenue"]


def _stats_row(row: dict | None) -> dict:
    row = row or {}
    return {
        "clicks": int(row.get("clicks") or 0),
        "unique": int(row.get("stream_unique_clicks") or 0),
        "bots": int(row.get("bots") or 0),
        "conversions": int(row.get("conversions") or 0),
        "revenue": float(row.get("revenue") or 0),
    }


def campaign_view(kt: KeitaroClient, cfg: Settings, campaign_id: int, interval: str) -> dict:
    campaign = kt.get_campaign(campaign_id)
    streams = sorted(kt.list_streams(campaign_id), key=lambda s: s.get("position", 0))
    offer_names = {o["id"]: o["name"] for o in kt.list_offers()}

    base = {
        "range": {"interval": interval, "timezone": cfg.report_timezone},
        "measures": MEASURES,
        "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
    }
    by_stream = {
        r["stream_id"]: r
        for r in kt.build_report({**base, "dimensions": ["stream_id"]}).get("rows", [])
    }
    by_offer = {
        (r["stream_id"], r["offer_id"]): r
        for r in kt.build_report({**base, "dimensions": ["stream_id", "offer_id"]}).get("rows", [])
    }

    out_streams = []
    for s in streams:
        offers = [
            {
                "offer_id": o["offer_id"],
                "name": offer_names.get(o["offer_id"], f"Оффер #{o['offer_id']}"),
                "share": o.get("share", 0),
                "state": o.get("state", "active"),
                "stats": _stats_row(by_offer.get((s["id"], o["offer_id"]))),
            }
            for o in s.get("offers", [])
        ]
        out_streams.append(
            {
                "id": s["id"],
                "name": s.get("name") or f"Поток {s['id']}",
                "position": s.get("position"),
                "state": s.get("state"),
                "schema": s.get("schema"),
                "action_type": s.get("action_type"),
                "action_payload": s.get("action_payload"),
                "filters": [
                    {"name": f["name"], "mode": f["mode"], "payload": f.get("payload")}
                    for f in s.get("filters", [])
                ],
                "offers": offers,
                "editable": s.get("schema") == "landings",
                "stats": _stats_row(by_stream.get(s["id"])),
            }
        )

    total = {k: 0 for k in ("clicks", "unique", "bots", "conversions")}
    total["revenue"] = 0.0
    for st in out_streams:
        for k in total:
            total[k] += st["stats"][k]

    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "alias": campaign.get("alias"),
        "url": f"{(campaign.get('domain') or '').rstrip('/')}/{campaign.get('alias', '')}",
        "group": campaign.get("group"),
        "state": campaign.get("state"),
        "interval": interval,
        "streams": out_streams,
        "total": total,
    }
