"""`/api/files` エンドポイントの結合テスト。"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from tests.conftest import make_client


async def test_upload_file_returns_meta(client: AsyncClient) -> None:
    res = await client.post(
        "/api/files",
        files={"file": ("photo.png", b"\x89PNG fake bytes", "image/png")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["filename"] == "photo.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(b"\x89PNG fake bytes")
    assert body["purpose"] == "uploads"
    assert body["content_url"] == f"/api/files/{body['id']}/content"


async def test_upload_file_sanitizes_path_traversal_filename(client: AsyncClient) -> None:
    res = await client.post(
        "/api/files",
        files={"file": ("../../etc/passwd", b"data", "text/plain")},
    )
    assert res.status_code == 201
    assert res.json()["filename"] == "passwd"


async def test_upload_empty_file_returns_400(client: AsyncClient) -> None:
    res = await client.post("/api/files", files={"file": ("empty.txt", b"", "text/plain")})
    assert res.status_code == 400


async def test_upload_disallowed_mime_type_returns_415(client: AsyncClient) -> None:
    res = await client.post(
        "/api/files",
        files={"file": ("virus.exe", b"data", "application/x-msdownload")},
    )
    assert res.status_code == 415


async def test_upload_file_too_large_returns_413(tmp_path: Path) -> None:
    async with make_client(tmp_path, settings_overrides={"upload_max_file_bytes": 10}) as (
        client,
        _state,
    ):
        res = await client.post(
            "/api/files",
            files={"file": ("big.txt", b"x" * 100, "text/plain")},
        )
        assert res.status_code == 413


async def test_download_file_returns_content_with_safety_headers(client: AsyncClient) -> None:
    upload_res = await client.post(
        "/api/files",
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    file_id = upload_res.json()["id"]

    res = await client.get(f"/api/files/{file_id}/content")
    assert res.status_code == 200
    assert res.content == b"hello world"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in res.headers["content-disposition"]
    assert "filename*=UTF-8''note.txt" in res.headers["content-disposition"]
    assert res.headers["content-security-policy"] == "default-src 'none'; sandbox"


async def test_download_missing_file_returns_404(client: AsyncClient) -> None:
    res = await client.get("/api/files/00000000-0000-0000-0000-000000000000/content")
    assert res.status_code == 404


async def test_delete_unattached_file_returns_204_and_removes_content(
    client: AsyncClient,
) -> None:
    upload_res = await client.post(
        "/api/files",
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    file_id = upload_res.json()["id"]

    delete_res = await client.delete(f"/api/files/{file_id}")
    assert delete_res.status_code == 204

    get_res = await client.get(f"/api/files/{file_id}/content")
    assert get_res.status_code == 404


async def test_delete_missing_file_returns_404(client: AsyncClient) -> None:
    res = await client.delete("/api/files/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404


async def test_delete_attached_file_returns_409(client: AsyncClient) -> None:
    upload_res = await client.post(
        "/api/files",
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    file_id = upload_res.json()["id"]

    create_res = await client.post("/api/conversations", json={})
    conversation_id = create_res.json()["id"]

    async with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "", "attachment_ids": [file_id]},
    ) as response:
        assert response.status_code == 200
        await response.aread()

    delete_res = await client.delete(f"/api/files/{file_id}")
    assert delete_res.status_code == 409
