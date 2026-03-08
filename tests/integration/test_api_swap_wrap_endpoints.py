from decimal import Decimal
from datetime import datetime
from fastapi.testclient import TestClient

from src.api.main import app
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation


client = TestClient(app)


def seed_swap(db_session):
    d = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("50"),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_api_seed",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(d)
    db_session.commit()

    for i in range(3):
        owner = f"add{i}"
        op = BRC20Operation(
            txid=f"tx_api_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="W",
            amount=Decimal("10"),
            from_address=owner,
            to_address=None,
            block_height=100,
            block_hash="h100",
            tx_index=i + 1,
            timestamp=datetime.utcnow(),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return="",
            parsed_json="{}",
            is_marketplace=False,
            is_multi_transfer=False,
            multi_transfer_step=None,
        )
        db_session.add(op)
        db_session.flush()
        pos = SwapPosition(
            owner_address=owner,
            pool_id="LOL-W",
            src_ticker="W",
            dst_ticker="LOL",
            amount_locked=Decimal("10"),
            lock_duration_blocks=10,
            lock_start_height=190,
            unlock_height=200 + i,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
    db_session.commit()


def test_swap_endpoints(db_session):
    seed_swap(db_session)

    # positions list
    r = client.get("/v1/indexer/swap/positions")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 3
    assert len(data["items"]) <= data["limit"]

    # owner positions
    r = client.get("/v1/indexer/swap/owner/add1/positions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(x["owner"] == "add1" for x in items)

    # expiring at height 201
    r = client.get("/v1/indexer/swap/expiring", params={"height_lte": 201})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(x["unlock_height"] <= 201 for x in items)

    # tvl
    r = client.get("/v1/indexer/swap/tvl/W")
    assert r.status_code == 200
    assert r.json()["ticker"] == "W"

    # pools
    r = client.get("/v1/indexer/swap/pools")
    assert r.status_code == 200
    pools = r.json()["items"]
    assert any(p["pool_id"] == "LOL-W" for p in pools)


def test_wrap_endpoints(db_session):
    # W deploy for tvl
    d = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("123"),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_wrap_api",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(d)
    db_session.commit()

    # contracts list (empty acceptable)
    r = client.get("/v1/indexer/w/contracts")
    assert r.status_code == 200

    # tvl
    r = client.get("/v1/indexer/w/tvl")
    assert r.status_code == 200
    assert r.json()["ticker"] == "W"

    # metrics
    r = client.get("/v1/indexer/w/metrics")
    assert r.status_code == 200
