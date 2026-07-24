"use client";

import { useState } from "react";
import { useLongPress } from "@/hooks/useLongPress";
import { PrimaryModeIcon, SecondaryModeIcon, PinIcon, TrashIcon, PencilIcon, EllipsisIcon, ArchiveIcon, RestoreIcon } from "@/components/ui/Icons";
import { dict } from "@/config";

export function ChatCard({
  session, isSelectMode, isSelected, onToggleSelect, onClick,
  onPin, onArchive, onDelete, onRestore, onRename, openMenuId, setOpenMenuId, isArchive
}: any) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.title);

  const { isTouch, handlers } = useLongPress(() => {
    if (!isEditing && !isSelectMode) {
      setOpenMenuId(session.id);
    }
  });

  const handleRenameSubmit = () => {
    if (editValue.trim() !== "") onRename(session.id, editValue.trim());
    setIsEditing(false);
  };

  const handleMenuClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.nativeEvent) {
      e.nativeEvent.stopImmediatePropagation();
    }
    setOpenMenuId(openMenuId === session.id ? null : session.id);
  };

  const isSecondary = session.type === dict.modes.secondary.id;
  const Icon = isSecondary ? SecondaryModeIcon : PrimaryModeIcon;
  // Only surface a tag for meaningful session kinds; the retired primary/
  // secondary modes are a backend detail, not a user-facing label (6B).
  const typeLabel =
    session.type === "onboarding" ? "Onboarding"
    : session.type === "analytic" ? "Analytic"
    : "";

  return (
    <div
      onClick={() => {
        if (isSelectMode) onToggleSelect(session.id);
        else if (!isEditing) onClick(session.id);
      }}
      {...handlers}
      onContextMenu={(e) => { if (isTouch && !isSelectMode) e.preventDefault(); }}
      className={`relative ${openMenuId === session.id ? 'z-50' : 'z-10'} group flex items-center gap-3 p-3 sm:p-4 rounded-xl bg-[var(--surface)] border hover:border-[var(--primary)] transition-all cursor-pointer select-none sm:select-auto ${session.pinned ? 'border-[var(--primary)]' : 'border-[var(--border)]'} ${isSelected ? 'ring-2 ring-[var(--primary)]' : ''} ${isArchive ? 'opacity-80 hover:opacity-100' : ''}`}
    >
      {isSelectMode && (
        <div className={`shrink-0 w-5 h-5 rounded-full border flex items-center justify-center transition-colors ${isSelected ? 'bg-[var(--primary)] border-[var(--primary)] text-[var(--primary-fg)]' : 'border-[var(--muted)]'}`}>
          {isSelected && <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>}
        </div>
      )}

      <div className={`shrink-0 w-10 h-10 rounded-full bg-[var(--background)] flex items-center justify-center border border-[var(--border)] transition-colors ${isArchive ? 'text-[var(--muted)] group-hover:text-[var(--primary)]' : 'text-[var(--primary)]'}`}>
        <Icon className="w-5 h-5" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          {session.pinned && !isSelectMode && <PinIcon className="w-4 h-4 text-[var(--primary)] shrink-0" />}
          
          <div className="flex items-center justify-between w-full min-w-0">
            {isEditing ? (
              <input 
                autoFocus type="text" value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={handleRenameSubmit}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRenameSubmit();
                  if (e.key === 'Escape') { setEditValue(session.title); setIsEditing(false); }
                }}
                onClick={(e) => e.stopPropagation()}
                className="w-full bg-[var(--background)] border border-[var(--primary)] text-[var(--foreground)] px-2 py-0.5 rounded focus:outline-none font-semibold min-w-0 text-sm"
              />
            ) : (
              <h3 className="font-bold text-sm text-[var(--foreground)] truncate group-hover:text-[var(--primary)] transition-colors">{session.title}</h3>
            )}
            <span className="text-xs text-[var(--muted)] shrink-0 hidden sm:block ml-2">{session.date}</span>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {typeLabel && (
            <span className="shrink-0 text-[10px] uppercase tracking-wider font-bold text-[var(--primary)] bg-[var(--primary)]/10 px-1.5 py-0.5 rounded">
              {typeLabel}
            </span>
          )}
          {session.modelLoadout && (
            <span
              title={`Model loadout: ${session.modelLoadout}`}
              className="shrink-0 text-[10px] font-mono lowercase tracking-tight text-[var(--muted)] bg-[var(--muted)]/10 px-1.5 py-0.5 rounded border border-[var(--border)]"
            >
              {session.modelLoadout}
            </span>
          )}
          <p className="text-xs text-[var(--muted)] truncate">{session.preview}</p>
        </div>
      </div>

      {!isSelectMode && (
        <div className="relative shrink-0 ml-2">
          <button 
            onClick={handleMenuClick} 
            className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--background)] rounded-md transition-colors"
          >
            <EllipsisIcon />
          </button>
          
          {openMenuId === session.id && (
            <div 
              onClick={(e) => e.stopPropagation()} 
              className="absolute right-0 top-full mt-1 w-48 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl py-1 z-50 animate-in fade-in zoom-in-95"
            >
              {isArchive ? (
                <>
                  <button onClick={(e) => { e.stopPropagation(); onRestore(session.id); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--background)] transition-colors">
                    <RestoreIcon className="w-4 h-4" /> Restore Chat
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); onDelete(session.id); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors">
                    <TrashIcon className="w-4 h-4" /> Delete Permanently
                  </button>
                </>
              ) : (
                <>
                  <button onClick={(e) => { e.stopPropagation(); onPin(session.id); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--background)] transition-colors">
                    <PinIcon className="w-4 h-4" /> {session.pinned ? "Unpin Chat" : "Pin Chat"}
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); setIsEditing(true); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--background)] transition-colors">
                    <PencilIcon className="w-4 h-4" /> Rename Chat
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); onArchive(session.id); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--background)] transition-colors">
                    <ArchiveIcon className="w-4 h-4" /> Archive Chat
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); onDelete(session.id); setOpenMenuId(null); }} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors">
                    <TrashIcon className="w-4 h-4" /> Delete
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}