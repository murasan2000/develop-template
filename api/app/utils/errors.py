"""エージェント層の例外を、ユーザーに見せてよいメッセージへ変換する純粋関数。

Gemini/ADK が投げる例外には、プロバイダの生ペイロード
（例: `UNAVAILABLE: 503 UNAVAILABLE. {'error': {'code': 503, ...}}`）が
そのまま文字列化されていることがある。これを画面にそのまま流すのはテンプレート
として不適切なので、`docs/api-contract.md` の `ErrorCode` に丸めて必ず定型文へ
変換する。原因調査に要る詳細（元の例外の文字列・code）はこの関数では捨てず、
呼び出し側（`app/servers/api.py`）でログに残す（この関数はログを持たない
純粋関数にして、単体テストしやすくしている）。

`app.services.agents` は並行実装中で、独自例外 `AgentInvocationError`
（`code: str` / `message: str` 属性を持つ）を公開する予定だが、実装が揃って
いない状態でもこちら側の型チェック・テストが独立して成立するよう、具象クラスは
import せず `code` 属性の有無で構造的に判定する（`app/types/agent_runtime.py`
の Protocol 方針と同じ考え方）。
"""

from __future__ import annotations

from app.types.api import ErrorCode

_MESSAGES: dict[ErrorCode, str] = {
    "model_overloaded": (
        "AIモデルが混み合っています。少し時間を置いてからもう一度送信してください。"
    ),
    "rate_limited": "利用量の上限に達しました。しばらく待ってから再試行してください。",
    "model_unavailable": ("AIモデルを利用できません。APIキーとモデル名の設定を確認してください。"),
    "internal": "応答の生成に失敗しました。時間を置いてもう一度お試しください。",
}

# ADK/Gemini 側が `code` に入れてくる値（大文字に正規化して比較する）。
# 例外クラス名がそのまま code 相当として来るケース（例: "ServerError"）も
# あるため、クラス名も同じ集合と突き合わせる。
_MODEL_OVERLOADED_CODES = frozenset({"UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED", "SERVERERROR"})
_RATE_LIMITED_CODES = frozenset({"RESOURCE_EXHAUSTED", "429", "TOO_MANY_REQUESTS"})
_MODEL_UNAVAILABLE_CODES = frozenset({"NOT_FOUND", "PERMISSION_DENIED", "INVALID_ARGUMENT"})


def _classify(raw_code: str | None, exc_type_name: str) -> ErrorCode:
    """`code` 属性と例外クラス名の両方を見て `ErrorCode` に分類する。"""
    normalized_code = raw_code.upper() if raw_code else None
    normalized_type = exc_type_name.upper()

    if normalized_code in _MODEL_OVERLOADED_CODES or normalized_type in _MODEL_OVERLOADED_CODES:
        return "model_overloaded"
    if normalized_code in _RATE_LIMITED_CODES or normalized_type in _RATE_LIMITED_CODES:
        return "rate_limited"
    if normalized_code in _MODEL_UNAVAILABLE_CODES or normalized_type in _MODEL_UNAVAILABLE_CODES:
        return "model_unavailable"
    return "internal"


def to_user_facing_error(exc: BaseException) -> tuple[ErrorCode, str]:
    """例外を `(code, message)` に変換する。

    `AgentInvocationError`（またはそれに構造的に一致する、文字列の `code`
    属性を持つ例外）は `code` を分類に使う。`code` 属性を持たない、あるいは
    未知の値を持つ例外は無条件で `internal` に落とす——安全側（「原因不明
    として扱う」）に倒すことで、判定漏れがユーザーに生の詳細を見せてしまう
    事故を防ぐ。
    """
    raw_code = getattr(exc, "code", None)
    raw_code_str = raw_code if isinstance(raw_code, str) else None
    code = _classify(raw_code_str, type(exc).__name__)
    return code, _MESSAGES[code]
