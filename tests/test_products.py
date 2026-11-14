"""Real SQLite + FastAPI tests for product management and FR-PRD-01..03 (no mocks)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.api.routes_products import (
    create_product,
    delete_or_hide_product,
    get_product,
    list_products,
    update_product,
)
from videocreator.app import create_app
from videocreator.db import get_conn, migrate


@pytest.mark.local
def test_product_crud_and_soft_hide_when_referenced(tmp_path: Path) -> None:
    db_file = tmp_path / "videocreator.db"
    migrate(db_file)

    pid1 = create_product(
        db_file,
        name="Nhẫn Bạc Xúc Xắc",
        material="Bạc S925 nguyên khối",
        facts={
            "stone": "Không đính đá",
            "size": "Bản 8mm, 12g",
            "craftsmanship": "Chạm khắc thủ công, oxy hoá",
            "price": "1.450.000đ",
        },
    )
    pid2 = create_product(
        db_file,
        name="Nhẫn Bạc Nhẫn Mới",
        material="Bạc S925",
        facts={"stone": "Onyx đen", "size": "Bản 6mm"},
    )

    items = list_products(db_file)
    assert sorted(p["id"] for p in items) == [pid1, pid2]
    p1 = get_product(db_file, pid1)
    assert p1 is not None
    assert p1["facts"]["craftsmanship"] == "Chạm khắc thủ công, oxy hoá"

    # Update product 1
    update_product(
        db_file,
        pid1,
        name="Nhẫn Bạc Xúc Xắc Bản Đặc Biệt",
        material="Bạc S950",
        facts={"stone": "Không đính đá", "size": "Bản 9mm, 14g"},
    )
    updated = get_product(db_file, pid1)
    assert updated is not None
    assert updated["name"] == "Nhẫn Bạc Xúc Xắc Bản Đặc Biệt"
    assert updated["material"] == "Bạc S950"
    assert updated["facts"]["size"] == "Bản 9mm, 14g"

    # Unreferenced product (#2) is hard-deleted
    outcome2 = delete_or_hide_product(db_file, pid2)
    assert outcome2 == "deleted"
    assert get_product(db_file, pid2) is None

    # Reference product #1 in footage -> delete must soft-hide (FR-PRD-02)
    with get_conn(db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (path, sha256, duration_s, width, height, orientation, product_ids_json, status)
            VALUES ('footage/1.mp4', 'abc123sha', 6.0, 1080, 1920, 'portrait', ?, 'imported')
            """,
            (f"[{pid1}]",),
        )

    outcome1 = delete_or_hide_product(db_file, pid1)
    assert outcome1 == "hidden"

    visible = list_products(db_file, include_hidden=False)
    assert visible == []

    all_items = list_products(db_file, include_hidden=True)
    assert len(all_items) == 1
    assert all_items[0]["id"] == pid1
    assert all_items[0]["hidden"] == 1


@pytest.mark.local
def test_products_web_routes(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        resp = client.get("/products")
        assert resp.status_code == 200
        assert "Quản lý sản phẩm" in resp.text

        post_resp = client.post(
            "/products",
            data={
                "name": "Mặt Dây Chuyền Bạc Thủ Công",
                "material": "Bạc S925",
                "stone": "Đá Mặt Trăng",
                "size": "3cm x 2cm",
                "craftsmanship": "Đánh bóng gương",
                "price": "",
                "notes": "Chế tác đơn chiếc",
            },
            follow_redirects=True,
        )
        assert post_resp.status_code == 200
        assert "Mặt Dây Chuyền Bạc Thủ Công" in post_resp.text
        assert "Đá Mặt Trăng" in post_resp.text
