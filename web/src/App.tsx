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

  return (
    <div className="app">
      {chat.error && <ErrorBanner message={chat.error.message} onDismiss={chat.dismissError} />}
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
          onSend={(text) => void chat.sendMessage(text)}
          onStop={chat.stopStreaming}
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onStartNew={chat.startNewConversation}
        />
      </div>
    </div>
  );
}

export default App;
