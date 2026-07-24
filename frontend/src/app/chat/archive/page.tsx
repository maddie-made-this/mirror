"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useToast } from "@/context/ToastContext";
import { ChatCard } from "@/components/features/chat/ChatHistoryShared";
import { BulkActionBar } from "@/components/shared/BulkActionBar";
import { ConfirmDeleteModal } from "@/components/shared/ConfirmDeleteModal";

interface ChatSession {
  id: string;
  type: string;
  title: string;
  preview: string;
  date: string;
  lastModified: number;
  pinned: boolean;
  archived?: boolean;
}

export default function ChatArchivePage() {
  const router = useRouter();
  const { showToast } = useToast();
  
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | "bulk" | null>(null);

  useEffect(() => {
    const stored = JSON.parse(localStorage.getItem("mirror_chats") || "[]");
    setChats(stored);

    const closeMenu = () => setOpenMenuId(null);
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, []);

  const updateChatState = (updatedChats: ChatSession[], message?: string, type: "success"|"info"|"error" = "success") => {
    setChats(updatedChats);
    localStorage.setItem("mirror_chats", JSON.stringify(updatedChats));
    if (message) showToast(message, type);
  };

  const restoreChat = (id: string) => updateChatState(chats.map(c => c.id === id ? { ...c, archived: false } : c), "Chat restored.", "success");
  
  const executeDelete = () => {
    if (deleteConfirmId === "bulk") {
      const count = selectedIds.size;
      const noun = count === 1 ? "chat" : "chats";
      updateChatState(chats.filter(c => !selectedIds.has(c.id)), `${count} ${noun} permanently deleted.`, "error");
      setIsSelectMode(false);
      setSelectedIds(new Set());
    } else if (deleteConfirmId) {
      updateChatState(chats.filter(c => c.id !== deleteConfirmId), "Chat permanently deleted.", "error");
    }
    setDeleteConfirmId(null);
  };

  const toggleSelection = (id: string) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  const handleBulkAction = (action: "unarchive" | "delete") => {
    if (action === "delete") {
      setDeleteConfirmId("bulk");
      return;
    }
    
    const count = selectedIds.size;
    const noun = count === 1 ? "chat" : "chats";

    const updatedChats = chats.map(chat => {
      if (selectedIds.has(chat.id) && action === "unarchive") return { ...chat, archived: false };
      return chat;
    });

    updateChatState(
      updatedChats,
      `${count} ${noun} restored.`,
      "success"
    );
    setIsSelectMode(false);
    setSelectedIds(new Set());
  };

  const archivedChats = chats.filter(c => c.archived).sort((a, b) => b.lastModified - a.lastModified);

  return (
    <div className="flex-1 flex flex-col h-full w-full relative overflow-y-auto bg-[var(--background)] pb-24">
      {deleteConfirmId && <ConfirmDeleteModal title={deleteConfirmId === "bulk" ? "Delete Selected Chats?" : "Delete Chat Session?"} message={deleteConfirmId === "bulk" ? `Are you sure you want to permanently delete ${selectedIds.size} chat sessions?` : "Are you sure you want to permanently delete this chat session?"} onConfirm={executeDelete} onClose={() => setDeleteConfirmId(null)} />}

      <div className="flex items-center justify-between p-4 sm:p-6 border-b border-[var(--border)] max-w-4xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <Link href="/chat" className="p-2 -ml-2 rounded-lg text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)] transition-all">
             <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <h1 className="text-2xl font-bold text-[var(--foreground)]">Archived Sessions</h1>
        </div>
        <button 
          onClick={() => { setIsSelectMode(!isSelectMode); setSelectedIds(new Set()); setOpenMenuId(null); }}
          className={`text-sm font-semibold hover:brightness-90 transition-colors border px-3 py-1.5 rounded-lg shadow-sm ${isSelectMode ? 'bg-[var(--primary)] text-[var(--primary-fg)] border-[var(--primary)]' : 'bg-[var(--surface)] text-[var(--foreground)] border-[var(--border)]'}`}
          disabled={archivedChats.length === 0}
        >
          {isSelectMode ? "Cancel" : "Edit"}
        </button>
      </div>

      <div className="max-w-4xl mx-auto w-full p-4 sm:p-6 flex flex-col gap-3">
        {archivedChats.length > 0 ? archivedChats.map(session => (
          <ChatCard 
            key={session.id} session={session} isSelectMode={isSelectMode} isSelected={selectedIds.has(session.id)}
            onToggleSelect={toggleSelection} onClick={(id: string) => router.push(`/chat/${id}`)}
            onRestore={restoreChat} onDelete={() => setDeleteConfirmId(session.id)}
            openMenuId={openMenuId} setOpenMenuId={setOpenMenuId} isArchive={true}
          />
        )) : (
          <div className="text-center p-8 border border-dashed border-[var(--border)] rounded-xl text-[var(--muted)] bg-[var(--surface)] w-full mt-4">
            No archived sessions found.
          </div>
        )}
      </div>

      {isSelectMode && (
        <BulkActionBar 
          selectedCount={selectedIds.size}
          onRestore={() => handleBulkAction("unarchive")} onDelete={() => handleBulkAction("delete")}
          isArchive={true}
        />
      )}
    </div>
  );
}