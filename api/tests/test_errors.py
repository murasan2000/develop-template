"""`app/utils/errors.py::to_user_facing_error` の単体テスト。"""

from __future__ import annotations

import pytest
from app.types.api import ErrorCode
from app.utils.errors import to_user_facing_error

_RAW_PROVIDER_PAYLOAD = (
    "UNAVAILABLE: 503 UNAVAILABLE. {'error': {'code': 503, "
    "'message': 'This model is currently experiencing high demand.', "
    "'status': 'UNAVAILABLE'}}"
)


class _CodedError(Exception):
    """`code`/`message` 属性を持つ、`AgentInvocationError` 相当のダミー例外。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("UNAVAILABLE", "model_overloaded"),
        ("INTERNAL", "model_overloaded"),
        ("DEADLINE_EXCEEDED", "model_overloaded"),
        ("RESOURCE_EXHAUSTED", "rate_limited"),
        ("NOT_FOUND", "model_unavailable"),
        ("PERMISSION_DENIED", "model_unavailable"),
        ("INVALID_ARGUMENT", "model_unavailable"),
        ("SOME_UNKNOWN_CODE", "internal"),
    ],
)
def test_to_user_facing_error_classifies_known_codes(code: str, expected: ErrorCode) -> None:
    exc = _CodedError(code=code, message=_RAW_PROVIDER_PAYLOAD)

    result_code, message = to_user_facing_error(exc)

    assert result_code == expected
    assert message  # 非空の日本語メッセージ
    # プロバイダの生ペイロードが漏れていないこと。
    assert "{'error'" not in message
    assert "503" not in message


def test_to_user_facing_error_falls_back_to_internal_for_unknown_exception() -> None:
    code, message = to_user_facing_error(RuntimeError("something broke"))

    assert code == "internal"
    assert "something broke" not in message


def test_to_user_facing_error_uses_exception_class_name_when_no_code_attribute() -> None:
    # ADK/genai 側の例外は、`code` 属性を持たず例外クラス名（例: ServerError）
    # だけで種別を表すことがある。
    class ServerError(Exception):
        pass

    code, message = to_user_facing_error(ServerError(_RAW_PROVIDER_PAYLOAD))

    assert code == "model_overloaded"
    assert "{'error'" not in message


def test_to_user_facing_error_messages_are_distinct_per_code() -> None:
    # 4 分類それぞれで異なる文面が返ること（同じ定型文に潰れていないこと）の確認。
    codes = ["UNAVAILABLE", "RESOURCE_EXHAUSTED", "NOT_FOUND", "totally-unknown"]
    messages = {to_user_facing_error(_CodedError(code, "x"))[1] for code in codes}
    assert len(messages) == 4
