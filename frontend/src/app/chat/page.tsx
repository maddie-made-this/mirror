"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { SearchIcon, PinIcon, ArchiveIcon } from "@/components/ui/Icons";
import { useToast } from "@/context/ToastContext";
import { ChatCard } from "@/components/features/chat/ChatHistoryShared";
import { BulkActionBar } from "@/components/shared/BulkActionBar";
import { ConfirmDeleteModal } from "@/components/shared/ConfirmDeleteModal";
import { dict } from "@/config";
import { apiClient } from "@/utils/apiClient";

interface ConversationSummary {
  conversation_id: string;
  session_type: string;
  title: string | null;
  pinned: boolean;
  last_at: string;
  first_user_message: string;
  last_response_text: string;
  model_loadout: string | null;
}

interface ChatSession {
  id: string;
  type: string;
  title: string;
  preview: string;
  date: string;
  lastModified: number;
  pinned: boolean;
  archived?: boolean;
  modelLoadout?: string;
}

export default function ChatDashboardPage() {
  const router = useRouter();
  const { showToast } = useToast();
  
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | "bulk" | null>(null);

  const loadChats = useCallback(async () => {
    // localStorage is a cache; the server (Postgres conversations table) is the
    // source of truth. Show the cached list immediately, then reconcile with the
    // server so history appears even on a fresh browser / after a storage clear.
    const cached: ChatSession[] = JSON.parse(localStorage.getItem("mirror_chats") || "[]");
    setChats(cached);

    try {
      const summaries = await apiClient<ConversationSummary[]>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/conversations`,
      );

      // Preserve client-only flags (archived) that the table doesn't track.
      const byId = new Map(cached.map((c) => [c.id, c]));
      const merged: ChatSession[] = summaries.map((s) => {
        const prior = byId.get(s.conversation_id);
        const title =
          s.title ||
          (s.first_user_message
            ? s.first_user_message.slice(0, 40) + (s.first_user_message.length > 40 ? "..." : "")
            : "New Session");
        return {
          id: s.conversation_id,
          type: s.session_type || dict.modes.primary.id,
          title,
          preview: (s.last_response_text || "").slice(0, 120),
          date: new Date(s.last_at).toLocaleDateString("en-US", {
            month: "short", day: "numeric", year: "numeric",
          }),
          lastModified: new Date(s.last_at).getTime(),
          pinned: s.pinned,
          archived: prior?.archived ?? false,
          modelLoadout: s.model_loadout || undefined,
        };
      });

      setChats(merged);
      localStorage.setItem("mirror_chats", JSON.stringify(merged));
    } catch {
      // Offline / signed-out (403) — keep the cached list already shown.
    }
  }, []);

  useEffect(() => {
    loadChats();

    const closeMenu = () => setOpenMenuId(null);
    document.addEventListener("click", closeMenu);
    
    // Listen for UserContext database swaps
    window.addEventListener("localDatabaseSwapped", loadChats);
    
    return () => {
      document.removeEventListener("click", closeMenu);
      window.removeEventListener("localDatabaseSwapped", loadChats);
    };
  }, [loadChats]);

  const updateChatState = (updatedChats: ChatSession[], message?: string, type: "success"|"info"|"error" = "success") => {
    setChats(updatedChats);
    localStorage.setItem("mirror_chats", JSON.stringify(updatedChats));
    if (message) showToast(message, type);
  };

  const togglePin = (id: string) => {
    const session = chats.find(c => c.id === id);
    updateChatState(chats.map(c => c.id === id ? { ...c, pinned: !c.pinned } : c), session?.pinned ? "Chat unpinned." : "Chat pinned.", "success");
  };

  const archiveChat = (id: string) => {
    updateChatState(chats.map(c => c.id === id ? { ...c, archived: true } : c), "Chat archived.", "info");
  };

  const executeDelete = () => {
    if (deleteConfirmId === "bulk") {
      const count = selectedIds.size;
      const noun = count === 1 ? "chat" : "chats";
      updateChatState(chats.filter(c => !selectedIds.has(c.id)), `${count} ${noun} deleted.`, "error");
      setIsSelectMode(false);
      setSelectedIds(new Set());
    } else if (deleteConfirmId) {
      updateChatState(chats.filter(c => c.id !== deleteConfirmId), "Chat deleted.", "error");
    }
    setDeleteConfirmId(null);
  };

  const saveRename = (id: string, newTitle: string) => {
    updateChatState(chats.map(c => c.id === id ? { ...c, title: newTitle } : c), "Chat renamed successfully.", "success");
  };

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  const handleBulkAction = (action: "archive" | "delete" | "pin") => {
    if (action === "delete") {
      setDeleteConfirmId("bulk");
      return;
    }
    
    const count = selectedIds.size;
    const noun = count === 1 ? "chat" : "chats";

    const updatedChats = chats.map(chat => {
      if (selectedIds.has(chat.id)) {
        if (action === "archive") return { ...chat, archived: true };
        if (action === "pin") return { ...chat, pinned: !chat.pinned };
      }
      return chat;
    });

    updateChatState(
      updatedChats,
      action === "archive" ? `${count} ${noun} archived.` : `${count} ${noun} pinned.`,
      action === "pin" ? "success" : "info"
    );
    setIsSelectMode(false);
    setSelectedIds(new Set());
  };

  const activeChats = chats.filter(c => !c.archived);
  const filteredChats = activeChats.filter(c => 
    c.title.toLowerCase().includes(searchQuery.toLowerCase()) || 
    c.preview.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const pinnedSessions = filteredChats.filter(c => c.pinned).sort((a, b) => b.lastModified - a.lastModified);
  const unpinnedSessions = filteredChats.filter(c => !c.pinned).sort((a, b) => b.lastModified - a.lastModified);

  const unpinnedIds = unpinnedSessions.map(c => c.id);
  const allUnpinnedSelected = unpinnedIds.length > 0 && unpinnedIds.every(id => selectedIds.has(id));

  const toggleSelectAllUnpinned = () => {
    const newSet = new Set(selectedIds);
    if (allUnpinnedSelected) {
      unpinnedIds.forEach(id => newSet.delete(id));
    } else {
      unpinnedIds.forEach(id => newSet.add(id));
    }
    setSelectedIds(newSet);
  };

  return (
    <div className="flex-1 w-full h-full overflow-y-auto overflow-x-hidden bg-transparent p-4 sm:p-6 lg:p-8 transition-colors duration-500 relative">
      
      {deleteConfirmId && <ConfirmDeleteModal title={deleteConfirmId === "bulk" ? "Delete Selected Chats?" : "Delete Chat Session?"} message={deleteConfirmId === "bulk" ? `Are you sure you want to permanently delete ${selectedIds.size} chat sessions?` : "Are you sure you want to permanently delete this chat session?"} onConfirm={executeDelete} onClose={() => setDeleteConfirmId(null)} />}

      <div className="max-w-4xl mx-auto flex flex-col gap-8 pb-24 w-full min-w-0">
        
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border)] pb-6 w-full min-w-0">
          <div className="w-full min-w-0">
            <h1 className="text-3xl font-bold text-[var(--foreground)] truncate">Chat History</h1>
            <p className="text-sm text-[var(--muted)] mt-1 truncate">Manage your unified timeline of learning states.</p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <Link href="/chat/archive" className="flex items-center gap-1.5 text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">
              <ArchiveIcon className="w-4 h-4" /> Archive
            </Link>
            <button 
              onClick={() => { setIsSelectMode(!isSelectMode); setSelectedIds(new Set()); setOpenMenuId(null); }}
              className={`text-sm font-semibold hover:brightness-90 transition-colors border px-3 py-1.5 rounded-lg shadow-sm ${isSelectMode ? 'bg-[var(--primary)] text-[var(--primary-fg)] border-[var(--primary)]' : 'bg-[var(--surface)] text-[var(--foreground)] border-[var(--border)]'}`}
            >
              {isSelectMode ? "Cancel" : "Edit"}
            </button>
          </div>
        </div>

        <div className="relative w-full min-w-0 -mt-2">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <SearchIcon className="w-5 h-5 text-[var(--muted)]" />
          </div>
          <input
            type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search titles or previews..."
            className="w-full pl-11 pr-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-xl text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all shadow-sm min-w-0"
          />
        </div>

        {pinnedSessions.length > 0 && (
          <div className="flex flex-col gap-3 w-full min-w-0">
            <h2 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-1 flex items-center gap-2">
              <PinIcon className="w-3.5 h-3.5" /> Pinned
            </h2>
            {pinnedSessions.map(session => (
              <ChatCard 
                key={session.id} session={session} isSelectMode={isSelectMode} isSelected={selectedIds.has(session.id)}
                onToggleSelect={toggleSelection} onClick={(id: string) => router.push(`/chat/${id}`)}
                onPin={togglePin} onArchive={archiveChat} onDelete={() => setDeleteConfirmId(session.id)} onRename={saveRename}
                openMenuId={openMenuId} setOpenMenuId={setOpenMenuId} isArchive={false}
              />
            ))}
            <hr className="border-[var(--border)] mt-4 mb-2" />
          </div>
        )}

        <div className="flex flex-col gap-3 w-full min-w-0">
          <h2 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-1">Recent Sessions</h2>
          {unpinnedSessions.length > 0 ? unpinnedSessions.map(session => (
            <ChatCard 
              key={session.id} session={session} isSelectMode={isSelectMode} isSelected={selectedIds.has(session.id)}
              onToggleSelect={toggleSelection} onClick={(id: string) => router.push(`/chat/${id}`)}
              onPin={togglePin} onArchive={archiveChat} onDelete={() => setDeleteConfirmId(session.id)} onRename={saveRename}
              openMenuId={openMenuId} setOpenMenuId={setOpenMenuId} isArchive={false}
            />
          )) : (
            <div className="text-center p-8 border border-dashed border-[var(--border)] rounded-xl text-[var(--muted)] bg-[var(--surface)] w-full">
              No recent sessions found.
            </div>
          )}
        </div>
      </div>

      {isSelectMode && (
        <BulkActionBar 
          selectedCount={selectedIds.size} hasUnpinned={unpinnedSessions.length > 0}
          onPin={() => handleBulkAction("pin")} onArchive={() => handleBulkAction("archive")} onDelete={() => handleBulkAction("delete")}
          onSelectAllUnpinned={toggleSelectAllUnpinned} allUnpinnedSelected={allUnpinnedSelected} isArchive={false}
        />
      )}
    </div>
  );
}