"""root agent（チャットエージェント）の定義。

設計原則: 「1 エージェント = 1 モジュール = 1 `build_*_agent()`」。
このモジュールは `Agent` インスタンスの組み立てにのみ責任を持ち、
`Runner` や `SessionService` の存在を一切知らない（それらの組み立ては
`runtime.py` に一元化する）。エージェントを増やすときは、共通の
BaseAgent を作るのではなく、このファイルと同じ形の新しいモジュールを
追加する。
"""

from __future__ import annotations

from google.adk import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.workflow import RetryConfig

from app.services.agents.prompts import CHAT_AGENT_DESCRIPTION, CHAT_AGENT_INSTRUCTION
from app.services.agents.tools import get_current_time

# ADK の `RetryConfig` の既定（initial_delay=1.0, backoff_factor=2.0,
# max_delay=60.0）は最大待ち時間が長すぎ、チャットの体感を損なうため、
# チャット向けに上限を絞った値を明示する。
_RETRY_INITIAL_DELAY_SECONDS = 1.0
_RETRY_BACKOFF_FACTOR = 2.0
_RETRY_MAX_DELAY_SECONDS = 8.0


def _build_retry_config(max_attempts: int) -> RetryConfig | None:
    """一時的な障害（5xx）だけに絞ったリトライ設定を組み立てる。

    `RetryConfig.exceptions=None`（既定）は全例外をリトライ対象にしてしまい、
    認証エラーや存在しないモデル名の指定のような、何度リトライしても直らない
    失敗まで無駄に待たされることになる。google-genai の例外階層は
    `APIError` を頂点に `ServerError`（5xx）と `ClientError`（4xx）に分かれて
    おり、`RetryConfig.exceptions` は例外の**クラス名の文字列**で照合する
    仕組み（`_normalize_exceptions` 参照）のため、ここではクラス名
    `"ServerError"` だけを指定して一時的な障害に絞る。

    429（RESOURCE_EXHAUSTED、クォータ超過）は本来リトライして回復し得るが、
    `ClientError` は 400/401/403 のような「何度やっても直らない」失敗と
    同じクラスを共有しており、クラス名だけでは区別できない。誤って
    回復不能な失敗まで繰り返し待たされないよう、ここでは `ClientError` を
    あえてリトライ対象に含めない。

    `max_attempts` が 1 以下ならリトライ自体を無効にする（`None` を返す。
    `Agent.retry_config=None` はリトライしないことを意味する）。
    """
    if max_attempts <= 1:
        return None
    return RetryConfig(
        max_attempts=max_attempts,
        initial_delay=_RETRY_INITIAL_DELAY_SECONDS,
        backoff_factor=_RETRY_BACKOFF_FACTOR,
        max_delay=_RETRY_MAX_DELAY_SECONDS,
        exceptions=["ServerError"],
    )


def build_chat_agent(*, model: str | BaseLlm, max_retry_attempts: int = 3) -> Agent:
    """root agent を組み立てる。

    モデル名は `runtime.py`（さらに遡ると設定値）から引数で受け取る。
    ここでモデル名をハードコードしないことで、LLM 設定を 1 箇所
    （呼び出し元）に集約する。`model` の型を ADK の `Agent.model` と同じ
    `str | BaseLlm` にしているのは、テストでフェイクの `BaseLlm` 実装を
    注入できるようにするため（実運用では常に Gemini のモデル名文字列を渡す）。

    `max_retry_attempts` は Gemini の一時的な障害（503 UNAVAILABLE など）に
    対するリトライ回数の上限。実際のリトライ設定は `_build_retry_config` に
    切り出し、`Agent.retry_config` として渡す。
    """
    return Agent(
        name="chat_agent",
        model=model,
        instruction=CHAT_AGENT_INSTRUCTION,
        description=CHAT_AGENT_DESCRIPTION,
        tools=[get_current_time],
        retry_config=_build_retry_config(max_retry_attempts),
    )
