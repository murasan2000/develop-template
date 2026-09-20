// 画面全体のチャット状態（会話一覧・選択中の会話・メッセージ・ストリーミング）を
// ここに閉じ込める。components/ 配下は表示に専念させ、状態や API 呼び出しの
// ロジックはこのフック 1 箇所にまとめることで、テンプレートとしての見通しを保つ。
import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import { ApiError } from '../api/client'; // instanceof チェック用に named import も併用する
import { useAttachments } from './useAttachments';
import type { Conversation, ErrorCode, FileMeta, Message } from '../types/api';
import { byUpdatedAtDesc } from '../utils/format';

// 再送で直る見込みがあるエラーだけ「再試行」ボタンを出す。model_unavailable
// （モデル名誤り・権限不足）や internal は設定やサーバ側の問題なので、
// 同じ内容を再送しても結果は変わらない——ユーザーに無駄な操作をさせないため
// あえて出さない。
const RETRYABLE_ERROR_CODES: ReadonlySet<ErrorCode> = new Set(['model_overloaded', 'rate_limited']);

// 送信直後・ストリーミング中の吹き出しは、まだ確定した Message（id や
// created_at を持つサーバー側の行）ではない。表示上は Message とほぼ同じ形で
// 扱えると components 側の実装が楽になるので、状態フラグだけ足した表示用の型を
// ここで定義する（docs/api-contract.md には無い、フロントエンド内部の型）。
export type DisplayMessage = Message | PendingMessage;

type PendingMessage = {
  id: string; // クライアント側だけの仮 id（"pending-user" / "pending-assistant"）
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  status: 'pending' | 'streaming';
  attachments: FileMeta[];
};

export function isPendingMessage(m: DisplayMessage): m is PendingMessage {
  return 'status' in m;
}

type ChatError = {
  message: string;
  // 会話一覧取得の失敗と送信失敗はバナーの出しどころが違うので区別する。
  scope: 'conversations' | 'messages' | 'stream';
  // 再送すれば直る見込みがあるエラーのときだけ、再送するテキストを持たせる。
  // components 側はこれが存在するかどうかだけを見て「再試行」ボタンの
  // 出し分けを判断できる（エラーコードの意味を components 側に持たせない）。
  retryText?: string;
};

// 送信中〜確定前のユーザー発言の表示用スナップショット。テキストと添付を
// まとめて 1 つの state にしているのは、両方が同時に現れて同時に消える
// （user イベント受信で確定する）ライフサイクルだからで、分けると同期が崩れる。
type PendingUser = { text: string; attachments: FileMeta[] };

export function useChat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [pendingUser, setPendingUser] = useState<PendingUser | null>(null);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const attachmentsHook = useAttachments();

  // 「今アクティブな会話はどれか」をコールバック内から同期的に参照するための ref。
  // state は再レンダー後にしか読めないため、ストリーム受信中に会話が切り替わった
  // ことを検知するには ref が必要（古いストリームの delta を捨てる判定に使う）。
  const activeIdRef = useRef<string | null>(null);
  // ref への書き込みはレンダー中に行えない（React のルール）ため、コミット後の
  // effect で同期する。ネットワーク応答が返ってくる頃には確実に反映済みになる。
  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  // 会話切り替え・アンマウント時に前のストリームを打ち切るための AbortController。
  const abortRef = useRef<AbortController | null>(null);

  // 契約:「部分的な結果を捨てない」方針は、クライアントの切断（停止ボタン）と
  // サーバ側のエラー（error イベント）のどちらにも等しく適用される。つまり
  // delta が 1 文字でも生成されていれば、サーバはそれを assistant メッセージ
  // として保存している可能性がある。ローカルの streamingText を破棄して
  // 空にしてしまうと「サーバには残っているのに画面だけ消える」ことになるため、
  // 対象の会話が今も表示中なら会話詳細を再取得してサーバの実データに揃える
  // （id・created_at を推測しない）。新しい取得経路は増やさず、選択時と同じ
  // api.getConversation を再利用する。
  const reconcileAfterInterruption = useCallback(async (conversationId: string) => {
    // 別の会話に切り替えられていたら、その会話はもう画面に出ていないので
    // 取りに行く必要がない（selectConversation が切り替え先を別途読み込む）。
    if (activeIdRef.current !== conversationId) return;
    try {
      const detail = await api.getConversation(conversationId);
      if (activeIdRef.current !== conversationId) return; // 取得中にさらに切り替えられた
      // 先に確定メッセージを反映してから pending/streaming をクリアする。
      // 逆順だと、再取得が終わるまでの一瞬テキストが画面から消えて見える。
      setMessages(detail.messages);
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? detail.conversation : c)).sort(byUpdatedAtDesc),
      );
      setPendingUser(null);
      setStreamingText(null);
    } catch {
      // 再取得にも失敗した場合は、ローカルに残っている表示をそのまま見せておく
      // （会話を開き直せばサーバの実データに揃う）。
    }
  }, []);

  // 初回マウント時に会話一覧を取得する。setState は必ず then/catch の中（＝
  // effect 本体の同期実行が終わったあとの非同期コールバック）で呼び、
  // アンマウント後の setState を `cancelled` フラグで防ぐ。
  useEffect(() => {
    let cancelled = false;
    api.listConversations().then(
      (list) => {
        if (cancelled) return;
        setConversations([...list].sort(byUpdatedAtDesc));
        setError(null);
        setIsLoadingConversations(false);
      },
      (e: unknown) => {
        if (cancelled) return;
        setError({ message: toErrorMessage(e), scope: 'conversations' });
        setIsLoadingConversations(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // アンマウント時に進行中のストリームを止める（画面遷移後もバックグラウンドで
  // fetch が生き続けて state 更新エラーになるのを防ぐ）。
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const selectConversation = useCallback(async (id: string) => {
    // 別の会話に移る＝いま受信中のストリームはもう画面に反映すべきでない。
    abortRef.current?.abort();
    setIsStreaming(false);
    setPendingUser(null);
    setStreamingText(null);
    setActiveId(id);
    setIsLoadingMessages(true);
    try {
      const detail = await api.getConversation(id);
      // 非同期取得中にさらに別の会話へ切り替えられていたら、古い結果は捨てる。
      if (activeIdRef.current !== id) return;
      setMessages(detail.messages);
      setError(null);
    } catch (e) {
      if (activeIdRef.current !== id) return;
      setError({ message: toErrorMessage(e), scope: 'messages' });
    } finally {
      if (activeIdRef.current === id) setIsLoadingMessages(false);
    }
  }, []);

  // 新規会話は API を叩かず、画面をまっさらな状態に戻すだけにする。実際の
  // 会話レコードは最初のメッセージ送信時に遅延作成する（未送信の空会話が
  // 一覧に溜まっていくのを避けるため）。
  const startNewConversation = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setActiveId(null);
    setMessages([]);
    setPendingUser(null);
    setStreamingText(null);
    setError(null);
  }, []);

  const removeConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (activeIdRef.current === id) {
          startNewConversation();
        }
      } catch (e) {
        setError({ message: toErrorMessage(e), scope: 'conversations' });
      }
    },
    [startNewConversation],
  );

  // sendMessage は useCallback の依存に isStreaming を含めたくない（不要な
  // 再生成を避けるため）ので、最新値を同期的に読める ref を別途持つ。
  const isStreamingRef = useRef(false);

  const sendMessage = useCallback(
    async (content: string, attachmentIds: string[]) => {
      const text = content.trim();
      // 本文が空でも添付があれば送れる（添付のみの送信を許すため）。
      if ((!text && attachmentIds.length === 0) || isStreamingRef.current) return;

      // 表示用の FileMeta はこの時点の attachmentsHook の状態から引く。
      // attachmentIds（サーバに送る ID）と実際に画面に見せる添付を同じ
      // ソースから作ることで、両者がずれない。
      const attachmentMetas = attachmentsHook.attachments
        .filter(
          (a): a is { localId: string; status: 'ready'; file: FileMeta } => a.status === 'ready',
        )
        .filter((a) => attachmentIds.includes(a.file.id))
        .map((a) => a.file);

      setError(null);
      setPendingUser({ text, attachments: attachmentMetas });
      setStreamingText('');
      setIsStreaming(true);
      isStreamingRef.current = true;

      // catch 節（中断時の再取得）からも参照するため try の外で宣言する。
      let conversationId: string | null = null;

      try {
        conversationId = activeIdRef.current;
        if (!conversationId) {
          const created = await api.createConversation();
          conversationId = created.id;
          activeIdRef.current = created.id;
          setActiveId(created.id);
          setConversations((prev) => [created, ...prev]);
        }

        const controller = new AbortController();
        abortRef.current = controller;
        // このストリームが「今の会話」宛てである間だけ画面に反映する。
        const cid = conversationId;
        const isStale = () => activeIdRef.current !== cid;

        await api.sendMessage(
          cid,
          text,
          attachmentIds,
          {
            onEvent: (evt) => {
              if (isStale()) return;
              switch (evt.event) {
                case 'user':
                  setPendingUser(null);
                  setMessages((prev) => [...prev, evt.data]);
                  // サーバが受理した確証が取れた時点でプレビューを消す。これより
                  // 早いと、送信に失敗したときに添付が画面から消えてしまう。
                  attachmentsHook.clear();
                  break;
                case 'delta':
                  setStreamingText((prev) => (prev ?? '') + evt.data.text);
                  break;
                case 'done': {
                  const { title: _title, ...message } = evt.data;
                  setStreamingText(null);
                  setMessages((prev) => [...prev, message]);
                  setConversations((prev) =>
                    prev
                      .map((c) =>
                        c.id === cid
                          ? { ...c, title: evt.data.title, updated_at: message.created_at }
                          : c,
                      )
                      .sort(byUpdatedAtDesc),
                  );
                  break;
                }
                case 'error':
                  // message はサーバ側でユーザー向け日本語に変換済みなので、
                  // ここで文面を作り直したり生ペイロードを混ぜたりしない。
                  // 添付付きの送信は再試行ボタンを出さない（D9）。ユーザー発言は
                  // 既に添付付きで永続化されており、同じ attachment_ids を
                  // 再送すると 409 になるため。
                  setError({
                    message: evt.data.message,
                    scope: 'stream',
                    retryText:
                      RETRYABLE_ERROR_CODES.has(evt.data.code) && attachmentIds.length === 0
                        ? text
                        : undefined,
                  });
                  // streamingText はここでは消さない（reconcileAfterInterruption が
                  // サーバの実データを取得したあとにまとめて確定させる）。
                  void reconcileAfterInterruption(cid);
                  break;
              }
            },
          },
          controller.signal,
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') {
          // 契約: クライアントが切断しても、そこまでの部分応答はサーバが
          // assistant メッセージとして保存する。何もせず return すると、画面には
          // 未確定の streamingText が残ったままになり、次の送信で
          // setStreamingText('') に上書きされて「サーバには保存されているのに
          // 画面だけ消える」壊れ方になる。error イベント時と同じ
          // reconcileAfterInterruption で表示をサーバの実データに揃える。
          if (conversationId) await reconcileAfterInterruption(conversationId);
          return;
        }
        setPendingUser(null);
        setStreamingText(null);
        setError({ message: toErrorMessage(e), scope: 'stream' });
      } finally {
        setIsStreaming(false);
        isStreamingRef.current = false;
        abortRef.current = null;
      }
    },
    [reconcileAfterInterruption, attachmentsHook],
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const dismissError = useCallback(() => setError(null), []);

  // error.retryText がある（= 再送で直る見込みがあるエラー）ときだけ有効。
  // 直前のユーザー発言をもう一度 sendMessage するだけで、同じ内容がもう 1 通
  // 永続化される（会話履歴に再送した事実が残る、素直な挙動でよしとする）。
  const retryLastMessage = useCallback(() => {
    const retryText = error?.retryText;
    if (!retryText) return;
    // retryText は添付なしの送信だったときだけ立つ（D9）ので、常に添付なしで
    // 再送してよい。
    void sendMessage(retryText, []);
  }, [error, sendMessage]);

  // 表示用に、確定済みメッセージへ「送信待ちのユーザー発言」「ストリーミング中の
  // 応答」を仮想メッセージとして連結する。components 側は DisplayMessage の
  // 配列だけを見ればよく、pending/streaming の状態を個別に気にしなくてよい。
  const displayMessages: DisplayMessage[] = [...messages];
  if (pendingUser !== null) {
    displayMessages.push({
      id: 'pending-user',
      conversation_id: activeId ?? '',
      role: 'user',
      content: pendingUser.text,
      created_at: new Date().toISOString(),
      status: 'pending',
      attachments: pendingUser.attachments,
    });
  }
  if (streamingText !== null) {
    displayMessages.push({
      id: 'pending-assistant',
      conversation_id: activeId ?? '',
      role: 'assistant',
      content: streamingText,
      created_at: new Date().toISOString(),
      status: 'streaming',
      attachments: [],
    });
  }

  return {
    conversations,
    isLoadingConversations,
    activeId,
    messages: displayMessages,
    isLoadingMessages,
    isStreaming,
    error,
    selectConversation,
    startNewConversation,
    removeConversation,
    sendMessage,
    stopStreaming,
    dismissError,
    retryLastMessage,
    // 送信前の添付プレビュー状態。ChatPane → Composer への props 経路を 1 本に
    // 保つため、独立フックとして App 側に併置せずここで再公開する。
    attachments: attachmentsHook.attachments,
    addAttachments: attachmentsHook.addFiles,
    removeAttachment: attachmentsHook.remove,
    isUploadingAttachments: attachmentsHook.isUploading,
    readyAttachmentIds: attachmentsHook.readyIds,
  };
}

function toErrorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return '不明なエラーが発生しました';
}
