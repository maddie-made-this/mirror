"use client";

import { Suspense, useState, useEffect, useCallback, useRef } from "react";
import { useUser } from "@/context/UserContext";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ChatBadge, ChatInput, ChatMessage } from "@/components/features/chat/ChatComponents";
import { CowriterChips } from "@/components/features/chat/CowriterChips";
import { dict } from "@/config";
import { useChat } from "@/hooks/useChat";
import { apiClient } from "@/utils/apiClient";

interface ConversationTurn {
  user_message: string;
  response_text: string;
  created_at: string;
  message_id?: string | null;  // AI turn id → serverId, so feedback works on history
  is_piece?: boolean;          // rendered in the generative register → gets chips
}

/**
 * The single chat page. Handles BOTH a brand-new conversation and an existing one,
 * branching on whether it has turns yet (the former `chat/new` was merged in here):
 *   - no turns  → seed: submit the home-page `?q=`, or show the initial greeting.
 *   - has turns → load the exchange from Postgres.
 * A fresh chat is just `/chat/<fresh-uuid>` with `?type=` (and maybe `?q=`); the
 * Postgres conversation row only materializes on the first user turn, so landing
 * here and leaving never spawns an empty conversation.
 */
function ChatContent() {
  const { settings } = useUser();
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const chatId = params.id as string;

  // The "why did that land?" analytic-branch chip is separately flag-gated (off by
  // default): the fork works, but it lands on a generic opener rather than one
  // framed around the piece, so it's held back until that UX is finished.
  // NEXT_PUBLIC_ENABLE_ANALYTIC_BRANCH=1 turns it on; ?whyland=1 enables it ad hoc.
  const showAnalyticBranch =
    (process.env.NEXT_PUBLIC_ENABLE_ANALYTIC_BRANCH === "1" ||
      searchParams.get("whyland") === "1");

  // Editing a user message is currently local-only — it does not survive a
  // refresh — so the edit control is hidden by default to avoid implying a
  // durable privacy scrub it can't yet deliver. Flip on once the edit persists.
  // NEXT_PUBLIC_ENABLE_MESSAGE_EDIT=1 turns it on; ?edit=1 enables it ad hoc.
  const showMessageEdit =
    (process.env.NEXT_PUBLIC_ENABLE_MESSAGE_EDIT === "1" ||
      searchParams.get("edit") === "1");

  // Fresh chats arrive with ?type= (and optionally ?q=) from the home page /
  // sidebar; existing chats carry their type in the localStorage chat list.
  const queryType = searchParams.get("type");
  const initialQuery = searchParams.get("q");

  const [sessionType, setSessionType] = useState(queryType || dict.modes.primary.id);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [savingToLibrary, setSavingToLibrary] = useState(false);

  const {
    messages, setMessages,
    inputValue, setInputValue,
    isLoading,
    chips, sendChip, resumeBeat, retryMessage, branchHere, saveToLibrary, sendFeedback,
    messagesEndRef,
    handleSendMessage,
    submitMessage,
    copyToClipboard, editMessage, deleteMessage, voteMessage,
  } = useChat(chatId, sessionType);

  const onBranch = useCallback(async () => {
    const id = await branchHere();
    if (id) router.push(`/chat/${id}`);
  }, [branchHere, router]);

  // "Narrated" = the conversation contains a generated piece (long-form AI turns,
  // or a regenerated beat). Used only to decide whether "Save to Library" applies —
  // the library is just the pinned, derived view of a conversation. The old
  // kept/canon distinction (a filtered "accepted story" vs the full stream) is
  // gone; every turn is simply shown.
  const recentAi = messages.filter(m => m.sender === "ai" && m.text).slice(-3);
  const avgAiLen = recentAi.length
    ? recentAi.reduce((s, m) => s + m.text.length, 0) / recentAi.length
    : 0;
  const isNarrated = avgAiLen > 280 || messages.some(m => m.superseded);
  const visibleMessages = messages;

  // Retry only belongs on the MOST RECENT AI beat: regenerate supersedes the
  // last beat in place, so a retry on an older message would silently redo the
  // newest one instead. Find that bubble's id and offer the control only there.
  const lastAiId = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].sender === "ai" && messages[i].serverId) return messages[i].id;
    }
    return undefined;
  })();

  const hasInitialized = useRef(false);

  const loadChat = useCallback(async () => {
    // Session type + title live in the localStorage chat-list metadata. If the
    // chat isn't there yet (fresh, or pre-hydration), keep the query/default type.
    const stored = JSON.parse(localStorage.getItem("mirror_chats") || "[]");
    const chat = stored.find((c: any) => c.id === chatId);
    if (chat?.type) setSessionType(chat.type);

    // Message content comes from the backend (Postgres). Retry once on a transient
    // failure (cold start / token not ready) so a single miss doesn't render blank.
    const fetchTurns = () =>
      apiClient<ConversationTurn[]>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/conversations/${chatId}/turns`,
      );

    let turns: ConversationTurn[] | null = null;
    try {
      turns = await fetchTurns();
    } catch {
      try {
        await new Promise((r) => setTimeout(r, 600));
        turns = await fetchTurns();
      } catch {
        turns = null;  // genuinely unreachable — leave existing messages intact
      }
    }

    if (turns && turns.length > 0) {
      // Existing conversation — load the exchange (user bubble + ai bubble each).
      // The AI bubble carries serverId (the turn's message_id) so per-message
      // check/x feedback works on loaded history, not only on live beats.
      const mapped = turns.flatMap((t, i) => [
        { id: i * 2, text: t.user_message, sender: "user" as const },
        {
          id: i * 2 + 1, text: t.response_text, sender: "ai" as const,
          vote: null, serverId: t.message_id ?? undefined,
        },
      ]);
      setMessages(mapped);
      // Re-arm the reactions for the beat this conversation ends on, so a piece
      // still offers its chips (and the retry target) after a reload.
      const last = turns[turns.length - 1];
      resumeBeat({
        text: last.response_text,
        serverId: last.message_id ?? undefined,
        bubbleId: (turns.length - 1) * 2 + 1,
        isPiece: !!last.is_piece,
      });
    } else if (!hasInitialized.current) {
      // Fresh conversation — seed it once (the former chat/new init path).
      hasInitialized.current = true;
      if (initialQuery) {
        // Submit the home-page query: adds the user bubble + loading bubble, then
        // swaps in the real response — and materializes the Postgres conversation.
        submitMessage(initialQuery);
      } else {
        const t = chat?.type ?? queryType ?? dict.modes.primary.id;
        let initialText = dict.chat.initialMessages.primary;
        if (t === dict.modes.secondary.id) initialText = dict.chat.initialMessages.secondary;
        else if (t === "onboarding") initialText = dict.chat.initialMessages.onboarding;
        setMessages([{ id: Date.now(), text: initialText, sender: "ai", vote: null }]);
      }
    }

    setIsInitialLoading(false);
    // submitMessage must stay a STABLE identity or this callback is recreated on
    // every send, re-running the effect below and refetching history mid-send —
    // which wipes the optimistic user bubble. See the inFlight ref in useChat.
  }, [chatId, initialQuery, queryType, submitMessage, setMessages, resumeBeat]);

  // loadChat is keyed on chatId; the component is also remounted per chatId (see
  // ChatPageInner's key), so this runs fresh for each conversation. Reload too
  // when the local DB is swapped (login/logout).
  useEffect(() => {
    loadChat();
    window.addEventListener("localDatabaseSwapped", loadChat);
    return () => window.removeEventListener("localDatabaseSwapped", loadChat);
  }, [loadChat]);

  // Keep the localStorage chat-list metadata fresh so the chat appears in history.
  // Preserves an existing entry's title/type/date/pinned; only derives them for a
  // brand-new entry. Message content itself lives in Postgres, not here.
  useEffect(() => {
    if (messages.length <= 1 || !chatId) return;
    const stored = JSON.parse(localStorage.getItem("mirror_chats") || "[]");
    const idx = stored.findIndex((c: any) => c.id === chatId);
    const existing = idx > -1 ? stored[idx] : null;
    const firstUserMessage = messages.find(m => m.sender === "user")?.text;
    const derivedTitle =
      sessionType === "onboarding"
        ? "Onboarding Interview"
        : firstUserMessage
          ? (firstUserMessage.length > 30 ? firstUserMessage.slice(0, 30) + "..." : firstUserMessage)
          : "New Session";
    const chatData = {
      id: chatId,
      type: existing?.type ?? sessionType,
      title: existing?.title ?? derivedTitle,
      preview: messages[messages.length - 1].text,
      date:
        existing?.date ??
        new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
      lastModified: Date.now(),
      pinned: existing?.pinned ?? false,
    };
    if (idx > -1) stored[idx] = chatData;
    else stored.push(chatData);
    localStorage.setItem("mirror_chats", JSON.stringify(stored));
  }, [messages, chatId, sessionType]);

  if (isInitialLoading) {
    return <div className="flex-1 w-full h-full bg-[var(--background)]" />;
  }

  return (
    <div className="flex flex-col h-full w-full relative overflow-hidden">
      <ChatBadge sessionType={sessionType} />

      {/* Save to Library — appears once the conversation contains a generated
          piece (isNarrated). Compiles the conversation's turns into a derived story; the
          library reads from those turns, so nothing is copied. */}
      {isNarrated && (
        <button
          onClick={async () => {
            if (savingToLibrary) return;
            setSavingToLibrary(true);
            const id = await saveToLibrary();
            setSavingToLibrary(false);
            if (id) router.push("/library");
          }}
          disabled={savingToLibrary}
          className="absolute top-4 right-4 sm:top-6 sm:right-6 z-10 px-3 py-1.5 rounded-full text-xs font-bold bg-[var(--surface)]/80 backdrop-blur-md border border-[var(--border)] text-[var(--foreground)] hover:border-[var(--primary)] transition-colors disabled:opacity-50"
          title="Save this conversation to your Library."
        >
          {savingToLibrary ? "Saving…" : "＋ Save to Library"}
        </button>
      )}

      <div className="flex-1 overflow-y-auto p-4 sm:p-6 pt-16 sm:pt-20 w-full bg-[var(--background)] transition-colors duration-500">
        <div className="max-w-4xl mx-auto flex flex-col gap-6">
          {visibleMessages.map((msg) => (
            <ChatMessage
              key={msg.id} msg={msg}
              onEdit={editMessage} onDelete={deleteMessage}
              onVote={voteMessage} onCopy={copyToClipboard}
              onFeedback={sendFeedback} onRetry={msg.id === lastAiId ? retryMessage : undefined}
              onHelpMeUnderstand={showAnalyticBranch ? onBranch : undefined}
              allowEdit={showMessageEdit}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* The chips render themselves only when there are chips, and chips exist
          only for a piece — so the register decides, not a mode flag. */}
      <CowriterChips chips={chips} onSendChip={sendChip} onBranch={onBranch} disabled={isLoading} showBranch={showAnalyticBranch} />

      <ChatInput
        inputValue={inputValue}
        setInputValue={setInputValue}
        handleSendMessage={handleSendMessage}
        sessionType={sessionType}
        enterToSend={settings.enterToSend}
      />
    </div>
  );
}

// Key the content on the conversation id so switching chats (or minting a fresh
// one) gives a clean component instance — fresh messages + init guard — instead of
// leaking the previous chat's state.
function ChatPageInner() {
  const params = useParams();
  return <ChatContent key={(params.id as string) || "new"} />;
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex-1 w-full h-full bg-[var(--background)]" />}>
      <ChatPageInner />
    </Suspense>
  );
}
