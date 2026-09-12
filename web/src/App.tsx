import { useState } from 'react';
import { ChatPane } from './components/chat/ChatPane';
import { ErrorBanner } from './components/common/ErrorBanner';
import { Sidebar } from './components/sidebar/Sidebar';
import { useChat } from './hooks/useChat';
import './App.css';

function App() {
  const chat = useChat();
  // モバイル幅でのドロワー開閉。デスクトップでは CSS 側で常時表示にする。
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const activeConversation = chat.conversations.find((c) => c.id === chat.activeId);

  // 会話一覧そのものが読めない（'conversations'）のは、特定の会話とは無関係な
  // 全画面レベルの障害なので画面上部の全体バナーで出す。会話の中身の読み込みや
  // 送信に関するエラー（'messages' / 'stream'）は、その会話の文脈の中で分かる
  // 位置（ChatPane 内・入力欄の上）に出す方が「どの操作が失敗したか」が伝わる。
  const globalError = chat.error?.scope === 'conversations' ? chat.error : null;
  const conversationError = chat.error && chat.error.scope !== 'conversations' ? chat.error : null;

  return (
    <div className="app">
      {globalError && <ErrorBanner message={globalError.message} onDismiss={chat.dismissError} />}
      <div className="app__body">
        <Sidebar
          conversations={chat.conversations}
          activeId={chat.activeId}
          isLoading={chat.isLoadingConversations}
          isOpen={isSidebarOpen}
          onSelect={(id) => {
            void chat.selectConversation(id);
            setIsSidebarOpen(false);
          }}
          onNew={() => {
            chat.startNewConversation();
            setIsSidebarOpen(false);
          }}
          onDelete={(id) => void chat.removeConversation(id)}
          onClose={() => setIsSidebarOpen(false)}
        />
        <ChatPane
          activeConversation={activeConversation}
          messages={chat.messages}
          isLoadingMessages={chat.isLoadingMessages}
          isStreaming={chat.isStreaming}
          error={conversationError}
          onSend={(text) => void chat.sendMessage(text)}
          onStop={chat.stopStreaming}
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onStartNew={chat.startNewConversation}
          onDismissError={chat.dismissError}
          onRetryError={chat.retryLastMessage}
        />
      </div>
    </div>
  );
}

export default App;
