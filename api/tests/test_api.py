"""API の結合テスト（DB は SQLite、エージェント層はフェイクに差し替え）。"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from app.servers.api import send_message
from app.servers.state import AppState
from app.services.chat.titles import DEFAULT_CONVERSATION_TITLE
from app.types.api import SendMessageRequest
from httpx import AsyncClient

from tests.conftest import make_client
from tests.fakes import AgentInvocationErrorStub, FakeChatAgentRuntime
from tests.sse_helpers import parse_sse_events


def _ends_with_utc_offset(value: str) -> bool:
    """ISO 8601 文字列が UTC オフセット（`Z` または `+00:00`）で終わっているか。"""
    return value.endswith("Z") or value.endswith("+00:00")


class _StubRequest:
    """`send_message` は `request.app.state.app_state` しか参照しないため、
    実際の ASGI リクエストを組み立てずに済むよう最小限のスタブで代用する。
    """

    def __init__(self, app_state: AppState) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(app_state=app_state))


async def test_health_ok(client: AsyncClient) -> None:
    res = await client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["model"] == "fake-model"


async def test_create_list_detail_delete_conversation(client: AsyncClient) -> None:
    create_res = await client.post("/api/conversations", json={"title": "最初の会話"})
    assert create_res.status_code == 201
    conversation = create_res.json()
    assert conversation["title"] == "最初の会話"
    conversation_id = conversation["id"]

    list_res = await client.get("/api/conversations")
    assert list_res.status_code == 200
    assert any(c["id"] == conversation_id for c in list_res.json())

    detail_res = await client.get(f"/api/conversations/{conversation_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["conversation"]["id"] == conversation_id
    assert detail["messages"] == []

    delete_res = await client.delete(f"/api/conversations/{conversation_id}")
    assert delete_res.status_code == 204

    after_delete_res = await client.get(f"/api/conversations/{conversation_id}")
    assert after_delete_res.status_code == 404


async def test_create_conversation_without_title_uses_default(client: AsyncClient) -> None:
    res = await client.post("/api/conversations", json={})
    assert res.status_code == 201
    assert res.json()["title"] == DEFAULT_CONVERSATION_TITLE


async def test_conversation_timestamps_are_utc_aware_on_create_and_reread(
    client: AsyncClient,
) -> None:
    """SQLite 経由で読み戻しても UTC オフセット付きのままであることを確認する。

    `sa.DateTime(timezone=True)` は SQLite だと読み戻し時に tzinfo を落とすため、
    API 境界（`app/types/api.py`）で正規化していないと、作成直後のレスポンス
    （Python 側の aware な値がそのまま出る）と GET での再読み込み（DB から
    読み直した naive な値が出る）とで `Z` の有無がずれてしまう。
    """
    create_res = await client.post("/api/conversations", json={})
    created = create_res.json()
    assert _ends_with_utc_offset(created["created_at"])
    assert _ends_with_utc_offset(created["updated_at"])

    detail_res = await client.get(f"/api/conversations/{created['id']}")
    conversation = detail_res.json()["conversation"]
    assert _ends_with_utc_offset(conversation["created_at"])
    assert _ends_with_utc_offset(conversation["updated_at"])

    # POST 直後と GET での再読み込みとで、同じ会話の created_at 文字列が
    # 一致すること（今回の不整合そのものを直接押さえる）。
    assert conversation["created_at"] == created["created_at"]


async def test_get_missing_conversation_returns_404(client: AsyncClient) -> None:
    missing_id = uuid.uuid4()
    res = await client.get(f"/api/conversations/{missing_id}")
    assert res.status_code == 404
    assert "detail" in res.json()


async def test_delete_missing_conversation_returns_404(client: AsyncClient) -> None:
    missing_id = uuid.uuid4()
    res = await client.delete(f"/api/conversations/{missing_id}")
    assert res.status_code == 404


async def test_send_message_missing_conversation_returns_404(client: AsyncClient) -> None:
    missing_id = uuid.uuid4()
    res = await client.post(f"/api/conversations/{missing_id}/messages", json={"content": "hello"})
    assert res.status_code == 404


async def test_send_message_streams_sse_and_persists_history(tmp_path: Path) -> None:
    runtime = FakeChatAgentRuntime(reply_chunks=["こんにちは", "、世界"])
    async with make_client(tmp_path, runtime=runtime) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "こんにちは、これはテストです"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            raw = await response.aread()

        events = parse_sse_events(raw.decode("utf-8"))
        event_names = [name for name, _ in events]
        assert event_names[0] == "user"
        assert event_names[-1] == "done"
        assert "error" not in event_names

        user_event = events[0][1]
        assert user_event["role"] == "user"
        assert user_event["content"] == "こんにちは、これはテストです"

        delta_texts = [data["text"] for name, data in events if name == "delta"]
        assert delta_texts == ["こんにちは", "、世界"]

        done_event = events[-1][1]
        assert done_event["role"] == "assistant"
        assert done_event["content"] == "こんにちは、世界"
        # 30 文字以内なので、最初のユーザー発言そのものがタイトルになる。
        assert done_event["title"] == "こんにちは、これはテストです"

        # runtime 側にもエージェント契約どおりの呼び出しが行われている。
        assert runtime.ensure_session_calls == [(conversation_id, "local-user")]
        assert runtime.stream_reply_calls == [
            (conversation_id, "local-user", "こんにちは、これはテストです")
        ]

        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        detail = detail_res.json()
        assert detail["conversation"]["title"] == "こんにちは、これはテストです"
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["content"] == "こんにちは、世界"


async def test_message_timestamps_are_utc_aware_after_reread(tmp_path: Path) -> None:
    """メッセージ送信後、GET で読み直した `created_at` も UTC オフセット付きであること。"""
    async with make_client(tmp_path) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "こんにちは"},
        ) as response:
            assert response.status_code == 200
            await response.aread()

        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        detail = detail_res.json()
        assert len(detail["messages"]) == 2
        for message in detail["messages"]:
            assert _ends_with_utc_offset(message["created_at"])


async def test_client_disconnect_mid_stream_saves_partial_reply(tmp_path: Path) -> None:
    """クライアント切断（`GeneratorExit`）時も、そこまでの部分応答が保存されること。

    `httpx.ASGITransport` は、テストクライアントがレスポンスを読むのを途中で
    やめても ASGI アプリ側のストリーミング生成器へ実際の切断を伝播しない
    （手元の検証では、クライアントが読むのを止めても生成器はバックグラウンドで
    最後まで実行され続けた）。そのため HTTP レベルでの切断は再現できない。
    本番で Starlette がクライアント切断を検知すると
    `StreamingResponse.body_iterator.aclose()` を呼ぶので、ここではそれを
    直接呼び出すことで同じ状況（`GeneratorExit` が送られる）を決定的に再現する。
    """
    runtime = FakeChatAgentRuntime(reply_chunks=["最初の一文", "続きの文"])
    async with make_client(tmp_path, runtime=runtime) as (client, state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        response = await send_message(
            uuid.UUID(conversation_id),
            SendMessageRequest(content="こんにちは"),
            _StubRequest(state),  # type: ignore[arg-type]
        )
        body_iterator = response.body_iterator

        await body_iterator.__anext__()  # "user" イベント
        await body_iterator.__anext__()  # 最初の "delta" イベント（"最初の一文"）

        # ここでクライアントが停止ボタンを押した（＝接続を切った）状況を再現する。
        await body_iterator.aclose()

        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        detail = detail_res.json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        # 受け取れたのは最初のチャンクだけなので、それだけが保存されているはず。
        assert detail["messages"][1]["content"] == "最初の一文"


async def test_send_message_error_mid_stream_saves_partial_reply(tmp_path: Path) -> None:
    runtime = FakeChatAgentRuntime(
        partial_before_fail="途中まで応答した",
        fail_with=RuntimeError("agent boom"),
    )
    async with make_client(tmp_path, runtime=runtime) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "エラーになるはず"},
        ) as response:
            assert response.status_code == 200
            raw = await response.aread()

        events = parse_sse_events(raw.decode("utf-8"))
        event_names = [name for name, _ in events]
        assert event_names[0] == "user"
        assert event_names[-1] == "error"
        assert "done" not in event_names

        # 素性の分からない例外は "internal" に落ち、元の例外メッセージは
        # そのまま画面に出さない（生の詳細はログ側の責務）。
        error_event = events[-1][1]
        assert error_event["code"] == "internal"
        assert "agent boom" not in error_event["message"]

        # 部分的に受け取れたテキストは履歴として残る（欠けない）。
        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        detail = detail_res.json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["content"] == "途中まで応答した"


async def test_send_message_model_overloaded_error_hides_raw_provider_payload(
    tmp_path: Path,
) -> None:
    """Gemini の 503（モデル混雑）が、生ペイロードを含まない定型文に変換されること。"""
    raw_provider_payload = (
        "UNAVAILABLE: 503 UNAVAILABLE. {'error': {'code': 503, "
        "'message': 'This model is currently experiencing high demand. "
        "Spikes in demand are usually temporary. Please try again later.', "
        "'status': 'UNAVAILABLE'}}"
    )
    runtime = FakeChatAgentRuntime(
        fail_with=AgentInvocationErrorStub(code="UNAVAILABLE", message=raw_provider_payload),
    )
    async with make_client(tmp_path, runtime=runtime) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "混み合っている時に送る"},
        ) as response:
            assert response.status_code == 200
            raw = await response.aread()

        raw_text = raw.decode("utf-8")
        # 生の 503 ペイロードがレスポンスのどこにも含まれていないこと。
        assert "{'error'" not in raw_text
        assert "UNAVAILABLE" not in raw_text

        events = parse_sse_events(raw_text)
        error_event = events[-1][1]
        assert error_event == {
            "message": (
                "AIモデルが混み合っています。少し時間を置いてからもう一度送信してください。"
            ),
            "code": "model_overloaded",
        }


async def test_send_message_with_attachment_reaches_user_event_and_agent(tmp_path: Path) -> None:
    """添付付き送信で `user` イベントに attachments が乗り、`stream_reply` に
    正しいバイト列（ファイル内容そのもの）が渡ること。
    """
    runtime = FakeChatAgentRuntime(reply_chunks=["了解しました"])
    async with make_client(tmp_path, runtime=runtime) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        upload_res = await client.post(
            "/api/files",
            files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        )
        file_id = upload_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "この画像を見て", "attachment_ids": [file_id]},
        ) as response:
            assert response.status_code == 200
            raw = await response.aread()

        events = parse_sse_events(raw.decode("utf-8"))
        user_event = events[0][1]
        assert user_event["attachments"] == [
            {
                "id": file_id,
                "filename": "photo.png",
                "mime_type": "image/png",
                "size_bytes": len(b"fake-png-bytes"),
                "purpose": "uploads",
                "created_at": user_event["attachments"][0]["created_at"],
                "content_url": f"/api/files/{file_id}/content",
            }
        ]

        done_event = events[-1][1]
        assert done_event["attachments"] == []

        # エージェント層へは実体のバイト列がそのまま渡っていること。
        assert len(runtime.stream_reply_attachment_calls) == 1
        [attachments] = runtime.stream_reply_attachment_calls
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "photo.png"
        assert attachments[0]["mime_type"] == "image/png"
        assert attachments[0]["data"] == b"fake-png-bytes"

        # 添付済みファイルは再度他のメッセージへ添付できない（409 のテストは
        # test_files_api.py 側にもあるが、ここでは会話履歴に残ることを確認する）。
        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        detail = detail_res.json()
        assert detail["messages"][0]["attachments"][0]["filename"] == "photo.png"


async def test_send_message_with_empty_content_and_attachment_succeeds(tmp_path: Path) -> None:
    """本文が空でも添付があれば送信できる（添付のみのメッセージ）。"""
    async with make_client(tmp_path) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        upload_res = await client.post(
            "/api/files",
            files={"file": ("diagram.png", b"png-bytes", "image/png")},
        )
        file_id = upload_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "", "attachment_ids": [file_id]},
        ) as response:
            assert response.status_code == 200
            raw = await response.aread()

        events = parse_sse_events(raw.decode("utf-8"))
        assert events[0][1]["content"] == ""
        assert events[0][1]["attachments"][0]["filename"] == "diagram.png"

        # D8: 本文が空のときはタイトルが最初の添付のファイル名になる。
        detail_res = await client.get(f"/api/conversations/{conversation_id}")
        assert detail_res.json()["conversation"]["title"] == "diagram.png"


async def test_send_message_empty_content_and_no_attachments_returns_400(
    client: AsyncClient,
) -> None:
    create_res = await client.post("/api/conversations", json={})
    conversation_id = create_res.json()["id"]

    res = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": ""},
    )
    assert res.status_code == 400


async def test_send_message_with_missing_attachment_id_returns_404(client: AsyncClient) -> None:
    create_res = await client.post("/api/conversations", json={})
    conversation_id = create_res.json()["id"]

    res = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={
            "content": "hello",
            "attachment_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert res.status_code == 404


async def test_send_message_with_already_attached_attachment_returns_409(
    tmp_path: Path,
) -> None:
    async with make_client(tmp_path) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        upload_res = await client.post(
            "/api/files",
            files={"file": ("note.txt", b"hello", "text/plain")},
        )
        file_id = upload_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "1回目", "attachment_ids": [file_id]},
        ) as response:
            assert response.status_code == 200
            await response.aread()

        res = await client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "2回目", "attachment_ids": [file_id]},
        )
        assert res.status_code == 409


async def test_delete_conversation_removes_attachment_records_and_content(
    tmp_path: Path,
) -> None:
    """会話を削除すると、その会話の添付ファイルの DB 行と実体の両方が消えること。"""
    async with make_client(tmp_path) as (client, _state):
        create_res = await client.post("/api/conversations", json={})
        conversation_id = create_res.json()["id"]

        upload_res = await client.post(
            "/api/files",
            files={"file": ("note.txt", b"hello", "text/plain")},
        )
        file_id = upload_res.json()["id"]

        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "", "attachment_ids": [file_id]},
        ) as response:
            assert response.status_code == 200
            await response.aread()

        delete_res = await client.delete(f"/api/conversations/{conversation_id}")
        assert delete_res.status_code == 204

        # ファイルの実体・メタデータのどちらも消えている（404）こと。
        get_res = await client.get(f"/api/files/{file_id}/content")
        assert get_res.status_code == 404
