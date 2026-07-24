"use client";

import { useState, useRef, useEffect } from "react";
import { useLongPress } from "@/hooks/useLongPress";
import { PrimaryModeIcon, CopyIcon, PencilIcon, TrashIcon, EllipsisIcon, TypingDots } from "@/components/ui/Icons";

export interface Message {
  id: number;
  text: string;
  sender: string;
  vote?: "up" | "down" | null;
  serverId?: string;       // backend message_id, for canon supersede + feedback
  superseded?: boolean;    // regenerated away — kept in full stream, out of canon
  feedback?: "check" | "x" | null;  // per-message check/x (B3)
}

// Session kind for display. primary/secondary are retired user-facing modes
// (6B) — they return "" so nothing mode-specific surfaces; only meaningful
// kinds (onboarding, the analytic branch) get a label.
export function getSessionLabel(sessionType: string): string {
  if (sessionType === "onboarding") return "Onboarding";
  if (sessionType === "analytic") return "Analytic";
  return "";
}

export function ChatBadge({ sessionType }: { sessionType: string }) {
  const label = getSessionLabel(sessionType) || "Mirror AI";

  return (
    <button className="group absolute top-4 right-4 sm:top-6 sm:right-6 px-3 py-1.5 bg-[var(--surface)]/80 backdrop-blur-md border border-[var(--border)] rounded-full text-xs font-bold text-[var(--foreground)] flex items-center gap-2 z-10 shadow-sm transition-colors duration-500 cursor-default focus:outline-none">
      <PrimaryModeIcon className="w-4 h-4 text-[var(--primary)]" /> {label}
    </button>
  );
}

// Upper bound for the auto-growing input. Past this the textarea stops
// growing and scrolls internally instead of taking over the screen.
const MAX_INPUT_HEIGHT = 160;

export function ChatInput({ inputValue, setInputValue, handleSendMessage, sessionType, enterToSend = true }: any) {
  const label = getSessionLabel(sessionType);
  const placeholder = label ? `Type your prompt for ${label}...` : "Type your message...";
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Resize to fit the content on every change (and shrink back after a send
  // clears the value). Capped at MAX_INPUT_HEIGHT, after which overflow scrolls.
  useEffect(() => {
  const el = textareaRef.current;
  if (!el) return;
  el.style.height = "auto";
  const next = Math.min(el.scrollHeight, MAX_INPUT_HEIGHT);
  el.style.height = `${next}px`;
  // Only show scrollbar once content exceeds the cap
  el.style.overflowY = el.scrollHeight > MAX_INPUT_HEIGHT ? "auto" : "hidden";
}, [inputValue]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
  if (e.key === "Enter") {
    if (enterToSend && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage(e);
    } else if (!enterToSend && e.shiftKey) {
      e.preventDefault();
      handleSendMessage(e);
    }
  }
};

  return (
    <div className="p-3 sm:p-4 border-t border-[var(--border)] bg-[var(--surface)] shrink-0 transition-colors duration-500">
      <form onSubmit={handleSendMessage} className="flex items-end gap-2 sm:gap-3 max-w-4xl mx-auto w-full relative">
        <textarea
          ref={textareaRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          inputMode="text"
          autoCapitalize="sentences"
          autoCorrect="on"
          spellCheck
          style={{ maxHeight: MAX_INPUT_HEIGHT }}
          className="flex-1 resize-none overflow-y-auto p-2 sm:p-3 border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] text-base leading-relaxed transition-colors duration-500"
        />
        <button
          type="submit"
          disabled={!inputValue.trim()}
          className="bg-[var(--primary)] text-[var(--primary-fg)] px-4 sm:px-6 py-2 sm:py-3 rounded-lg hover:brightness-90 font-semibold transition-all duration-500 text-sm sm:text-base shrink-0 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
        >
          Send
        </button>
      </form>
    </div>
  );
}

export function ChatMessage({ msg, onEdit, onDelete, onVote, onCopy, isCopied, onFeedback, onRetry, onHelpMeUnderstand, allowEdit = false }: any) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(msg.text);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showTouchUserMenu, setShowTouchUserMenu] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const [retryOpen, setRetryOpen] = useState(false);
  const [retryNote, setRetryNote] = useState("");

  const isUser = msg.sender === "user";

  const { isTouch, handlers } = useLongPress(() => {
    if (isUser && !isEditing) setShowTouchUserMenu(true);
  });

  const handleSave = () => {
    onEdit(msg.id, editValue);
    setIsEditing(false);
  };

  return (
    <div className={`flex w-full group ${isUser ? "justify-end" : "justify-start"}`}>
      
      {showTouchUserMenu && (
        <div className="fixed inset-0 z-10" onClick={() => setShowTouchUserMenu(false)} />
      )}

      <div className={`relative flex max-w-[90%] sm:max-w-[80%] ${isUser && !isTouch && !isEditing ? "flex-row-reverse items-center gap-2" : "flex-col items-start"}`}>
        
        {isEditing ? (
          <div className="w-full bg-[var(--surface)] border border-[var(--border)] p-3 rounded-xl shadow-sm transition-colors duration-500 z-10">
            <textarea 
              className="w-full bg-transparent text-[var(--foreground)] focus:outline-none resize-none min-h-[80px] text-sm"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
            />
            <div className="flex justify-end gap-2 mt-2">
              <button onClick={() => setIsEditing(false)} className="px-3 py-1 text-xs rounded border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--background)]">Cancel</button>
              <button onClick={handleSave} className="px-3 py-1 text-xs rounded bg-[var(--primary)] text-[var(--primary-fg)] hover:brightness-90">Save</button>
            </div>
          </div>
        ) : (
          <>
            <div
              {...handlers}
              className={`p-4 rounded-xl shadow-sm transition-colors duration-500 border z-10 ${
                isUser
                  ? "bg-[var(--bubble-bg)] text-[var(--bubble-fg)] border-[var(--bubble-border)] select-none sm:select-auto"
                  : "bg-[var(--surface)] text-[var(--foreground)] border-[var(--ai-border)]"
              }`}
            >
              {/* Loading bubble (id -1) or an AI bubble still awaiting its first
                  streamed token → animated typing dots instead of static text. */}
              {!isUser && (msg.id === -1 || msg.text === "") ? <TypingDots /> : msg.text}
            </div>
          </>
        )}

        {!isEditing && isUser && !isTouch && (
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
            <button onClick={() => onCopy(msg.id, msg.text)} className={`p-1.5 rounded transition-colors ${isCopied ? "text-[var(--primary)]" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]"}`}>
              <CopyIcon filled={isCopied} />
            </button>
            {/* Edit is flag-gated (allowEdit): the edit is currently local-only and
                does not survive a refresh, so it's hidden until it persists. */}
            {allowEdit && (
              <button onClick={() => setIsEditing(true)} className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)] rounded">
                <PencilIcon />
              </button>
            )}

            <div className="relative">
              <button 
                onClick={(e) => { e.stopPropagation(); setIsMenuOpen(!isMenuOpen); }} 
                onBlur={() => setTimeout(() => setIsMenuOpen(false), 200)}
                className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)] rounded"
              >
                <EllipsisIcon />
              </button>
              {isMenuOpen && (
                <div className="absolute right-0 top-full mt-1 w-40 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl py-1 z-20 animate-in fade-in zoom-in-95">
                  <button onClick={() => onDelete(msg.id)} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors">
                    <TrashIcon className="w-4 h-4" /> Delete
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {isUser && isTouch && showTouchUserMenu && (
          <div className="absolute right-0 top-full mt-2 w-48 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl py-1 z-20 flex flex-col animate-in fade-in zoom-in-95">
            <button onClick={() => { onCopy(msg.id, msg.text); setShowTouchUserMenu(false); }} className="flex items-center gap-3 w-full text-left px-4 py-3 text-sm text-[var(--foreground)] hover:bg-[var(--background)]">
              <CopyIcon className="w-4 h-4" filled={isCopied} /> Copy Message
            </button>
            {allowEdit && (
              <button onClick={() => { setIsEditing(true); setShowTouchUserMenu(false); }} className="flex items-center gap-3 w-full text-left px-4 py-3 text-sm text-[var(--foreground)] hover:bg-[var(--background)]">
                <PencilIcon className="w-4 h-4" /> Edit Message
              </button>
            )}
            <button onClick={() => { onDelete(msg.id); setShowTouchUserMenu(false); }} className="flex items-center gap-3 w-full text-left px-4 py-3 text-sm text-red-500 hover:bg-red-500/10">
              <TrashIcon className="w-4 h-4" /> Delete Message
            </button>
          </div>
        )}

        {!isEditing && !isUser && (
          <div className={`flex flex-col gap-1 mt-1 w-full transition-opacity ${isTouch || msg.feedback ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
          <div className="flex items-center gap-1">
            {/* Per-message check / x (B3): "right for me" vs "not right for me" —
                fit, not a quality rating. Only on completed AI beats (serverId). */}
            {msg.serverId && onFeedback && (
              <>
                <button
                  title="This is right for me"
                  onClick={() => onFeedback(msg, "check")}
                  className={`p-1.5 rounded transition-colors text-base leading-none ${msg.feedback === "check" ? "text-emerald-400" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]"}`}
                >
                  ✓
                </button>
                <button
                  title="Not right for me"
                  onClick={() => { onFeedback(msg, "x"); setNoteOpen(true); }}
                  className={`p-1.5 rounded transition-colors text-base leading-none ${msg.feedback === "x" ? "text-rose-400" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]"}`}
                >
                  ✕
                </button>
              </>
            )}
            {/* Retry the beat. Opens the same note box as ✕, but the note STEERS
                the new take rather than only recording a reaction — rerolling an
                identical prompt and hoping is not a retry. */}
            {msg.serverId && onRetry && (
              <button
                title="Try this again — optionally say what to change"
                onClick={() => setRetryOpen(true)}
                className="p-1.5 rounded transition-colors text-base leading-none text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]"
              >
                ↻
              </button>
            )}
            <button onClick={() => onCopy(msg.id, msg.text)} className={`p-1.5 rounded transition-colors ${isCopied ? "text-[var(--primary)]" : "text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)]"}`}>
              <CopyIcon filled={isCopied} />
            </button>
            <div className="relative">
              <button 
                onClick={(e) => { e.stopPropagation(); setIsMenuOpen(!isMenuOpen); }} 
                onBlur={() => setTimeout(() => setIsMenuOpen(false), 200)}
                className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--surface)] rounded"
              >
                <EllipsisIcon />
              </button>
              {isMenuOpen && (
                <div className="absolute left-0 top-full mt-1 w-40 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-xl py-1 z-20 animate-in fade-in zoom-in-95">
                  <button onClick={() => onDelete(msg.id)} className="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors">
                    <TrashIcon className="w-4 h-4" /> Delete
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* After a check: the analytic-branch entry surfaces here. */}
          {msg.feedback === "check" && onHelpMeUnderstand && (
            <button
              onClick={() => onHelpMeUnderstand(msg)}
              className="text-xs text-[var(--primary)] hover:underline text-left mt-0.5"
            >
              help me understand this →
            </button>
          )}

          {/* After an x: an always-acceptable note box. Delivery-tuning only. */}
          {noteOpen && (
            <form
              onSubmit={(e) => { e.preventDefault(); onFeedback?.(msg, "x", note.trim() || undefined); setNoteOpen(false); setNote(""); }}
              className="flex items-center gap-2 mt-1 w-full max-w-md"
            >
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What was off? (optional)"
                className="flex-1 text-sm px-2 py-1 rounded border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                autoFocus
              />
              <button type="submit" className="text-xs px-2 py-1 rounded bg-[var(--primary)] text-[var(--primary-fg)] hover:brightness-90">Send</button>
              <button type="button" onClick={() => { setNoteOpen(false); setNote(""); }} className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]">Skip</button>
            </form>
          )}

          {/* Retry's note box. Same shape as the x note, but this text is handed
              to the model as the instruction for the new take. */}
          {retryOpen && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                onRetry?.(msg, retryNote.trim() || undefined);
                setRetryOpen(false); setRetryNote("");
              }}
              className="flex items-center gap-2 mt-1 w-full max-w-md"
            >
              <input
                value={retryNote}
                onChange={(e) => setRetryNote(e.target.value)}
                placeholder="What should change? (optional)"
                className="flex-1 text-sm px-2 py-1 rounded border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                autoFocus
              />
              <button type="submit" className="text-xs px-2 py-1 rounded bg-[var(--primary)] text-[var(--primary-fg)] hover:brightness-90">Retry</button>
              <button type="button" onClick={() => { setRetryOpen(false); setRetryNote(""); }} className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]">Cancel</button>
            </form>
          )}
          </div>
        )}
      </div>
    </div>
  );
}