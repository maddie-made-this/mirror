import { useState, useRef, useEffect, useCallback } from "react";
import { useToast } from "@/context/ToastContext";
import { useUser } from "@/context/UserContext";
import { Message } from "@/components/features/chat/ChatComponents";
import { apiClient, getAccessToken } from "@/utils/apiClient";
import type { Chip } from "@/types/graph";

const LOADING_ID = -1;
const ACTIVE_NODE_DECAY_TURNS = 3;  // a node stays "active" for this many turns

export function useChat(conversationId: string, sessionType: string) {
  const { showToast } = useToast();
  const { fullName } = useUser();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [warming, setWarming] = useState(false);  // P5.4: cold-start "warming up" state
  const [chips, setChips] = useState<Chip[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Re-entrancy guard for submitMessage, mirrored as a ref.
  //
  // `isLoading` is state because the UI renders from it, but submitMessage only
  // ever READS it to bail on a double-send. Putting it in the useCallback deps
  // made submitMessage a NEW function on every send, which cascaded: the chat
  // page's loadChat depends on submitMessage, the effect that calls loadChat
  // depends on loadChat, so starting a send re-ran loadChat, which refetched
  // turns from the server — and the server does not have the in-flight turn yet.
  // setMessages(mapped) then clobbered the optimistic user bubble, leaving the
  // typing indicator alone on screen until the response landed and the same
  // cascade re-ran with the turn now persisted.
  //
  // The first message of a fresh conversation was immune (no turns yet, so
  // loadChat takes the seed branch and never calls setMessages(mapped)), which
  // is exactly why the bug only showed from the second message on.
  const inFlight = useRef(false);

  // Map of node_id -> turns_since_mentioned. Pruned each turn.
  const activeNodes = useRef<Map<string, number>>(new Map());
  // The last completed AI beat — server message_id + client bubble id — so a
  // "regenerate" chip can drop it from canon.
  const lastBeat = useRef<{ serverId: string; bubbleId: number } | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Fetch the three reaction chips for a beat. Chips follow the REGISTER, not a
  // mode: any turn the director rendered as a piece gets them, and a
  // conversational turn doesn't. (They used to be gated on a "cowriter" flag
  // that shipped off, so nothing ever showed them.)
  const loadChips = useCallback(async (beat: string) => {
    if (!beat.trim()) return;
    try {
      const res = await apiClient<{ chips: Chip[] }>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/messages/chips`,
        { data: { conversation_id: conversationId, beat } },
      );
      setChips(res.chips ?? []);
    } catch {
      setChips([]);
    }
  }, [conversationId]);

  // Core send — accepts the message text directly so both the form handler and
  // the home-page auto-submit effect can call it. `regenerateOf` (P1.4) is the prior
  // beat's server message_id when this send is a regeneration: the backend joins the new
  // take to that beat's group (so the ‹1/3› variant picker populates) and supersedes the
  // prior takes — no separate /supersede call needed.
  const submitMessage = useCallback(async (
    userMessage: string,
    opts?: { regenerateOf?: string; replaceBubbleId?: number; continuePiece?: boolean },
  ) => {
    if (!userMessage.trim() || inFlight.current) return;
    inFlight.current = true;

    // A regenerate REPLACES the beat it redoes: the chip's steering instruction is
    // not something the user said, so it gets no user bubble, and the take being
    // redone is removed rather than left above its own replacement. Without this a
    // retry read as three bubbles — the old take, the instruction posing as a user
    // message, and the new take.
    const isRegen = !!opts?.regenerateOf;

    setChips([]);  // clear the previous beat's chips while the next is generated
    setMessages(prev => [
      ...prev.filter(m =>
        m.id !== LOADING_ID && !(isRegen && m.id === opts?.replaceBubbleId)
      ),
      ...(isRegen ? [] : [{ id: Date.now(), text: userMessage, sender: "user" as const }]),
      { id: LOADING_ID, text: "...", sender: "ai" as const, vote: null },
    ]);
    setIsLoading(true);

    // Age existing active nodes; drop expired.
    const aged = new Map<string, number>();
    for (const [id, age] of activeNodes.current) {
      if (age + 1 < ACTIVE_NODE_DECAY_TURNS) aged.set(id, age + 1);
    }
    activeNodes.current = aged;
    const activeIds = Array.from(activeNodes.current.keys());

    // Stable per-message id — a retry of this exact send reuses it so the
    // server dedups instead of processing the message twice.
    const clientMessageId = crypto.randomUUID();

    let finishedBeat:
      | { text: string; serverId: string; bubbleId: number; isPiece: boolean }
      | null = null;

    try {
      const token = await getAccessToken();

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/messages/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message: userMessage,
            conversation_id: conversationId,
            client_message_id: clientMessageId,
            active_node_ids: activeIds,
            user_display_name: fullName,
            ...(opts?.regenerateOf ? { regenerate_of: opts.regenerateOf } : {}),
            // Tells the server this turn continues a piece. Register detection
            // reads the message text, and a chip instruction reads as ordinary
            // conversation — without this the piece drops to conversational on
            // its second beat and the chips never come back.
            ...(opts?.continuePiece ? { continue_piece: true } : {}),
          }),
        },
      );

      if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";          // SSE frame accumulator
      let aiText = "";       // running response text
      let promptContext: unknown = null;  // captured from the debug "context" event
      const aiId = Date.now();

      // Swap the loading bubble for an empty AI bubble we fill as tokens arrive.
      setMessages(prev => [
        ...prev.filter(m => m.id !== LOADING_ID),
        { id: aiId, text: "", sender: "ai", vote: null },
      ]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        const frames = acc.split("\n\n");
        acc = frames.pop() || "";   // last partial frame stays buffered

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data: ")) continue;
          const evt = JSON.parse(line.slice(6));

          if (evt.type === "warming") {
            // P5.4: serverless cold start — the first token is slow. Show an honest
            // "warming up" state instead of a dead spinner; cleared on the first token.
            setWarming(true);
          } else if (evt.type === "token") {
            setWarming(false);
            aiText += evt.text;
            setMessages(prev =>
              prev.map(m => (m.id === aiId ? { ...m, text: aiText } : m))
            );
          } else if (evt.type === "safety_override") {
            aiText = evt.text;
            setMessages(prev =>
              prev.map(m => (m.id === aiId ? { ...m, text: aiText } : m))
            );
          } else if (evt.type === "context") {
            promptContext = evt.payload;
          } else if (evt.type === "done" && evt.payload) {
            // Stash the debug context onto the payload for the dev panel.
            const response = {
              ...evt.payload,
              prompt_context: evt.payload.prompt_context ?? promptContext,
            };
            // Tag the bubble with its server id so canon supersede can target it.
            setMessages(prev =>
              prev.map(m => (m.id === aiId ? { ...m, serverId: response.message_id } : m))
            );
            finishedBeat = {
              text: response.response_text,
              serverId: response.message_id,
              bubbleId: aiId,
              isPiece: !!response.is_piece,
            };
            for (const n of [...response.nodes_created, ...response.nodes_updated]) {
              activeNodes.current.set(n.id, 0);
            }
            // Message content lives in Postgres; localStorage keeps only the
            // chat-list metadata. Refresh this conversation's preview + time.
            const stored = JSON.parse(localStorage.getItem("mirror_chats") || "[]");
            const idx = stored.findIndex((c: any) => c.id === conversationId);
            if (idx > -1) {
              stored[idx].preview = response.response_text.slice(0, 120);
              stored[idx].lastModified = Date.now();
              localStorage.setItem("mirror_chats", JSON.stringify(stored));
            }
            window.dispatchEvent(new CustomEvent("graphUpdated", { detail: response }));
            window.dispatchEvent(new CustomEvent("messageDebug", { detail: response }));
          } else if (evt.type === "error") {
            throw new Error(evt.detail || "stream error");
          }
        }
      }
    } catch (err: any) {
      setMessages(prev => prev.filter(m => m.id !== LOADING_ID && m.text !== ""));
      showToast(err.message || "Failed to get response", "error");
    } finally {
      inFlight.current = false;
      setIsLoading(false);
      setWarming(false);
    }

    // After the beat completes, remember it and fetch fresh reaction chips.
    if (finishedBeat) {
      lastBeat.current = { serverId: finishedBeat.serverId, bubbleId: finishedBeat.bubbleId };
      // Only pieces get chips — reacting to "advance / regenerate / wildcard"
      // makes no sense against a conversational reply.
      if (finishedBeat.isPiece) void loadChips(finishedBeat.text);
    }
    // NOTE: `isLoading` is deliberately NOT a dependency — see the inFlight ref
    // above. Adding it back re-introduces the vanishing-message bug.
  }, [conversationId, showToast, fullName, loadChips]);

  // Re-arm the chip row for a beat loaded from history, so reopening a
  // conversation that ends on a piece still offers the reactions (and a retry)
  // instead of going blank until you send something else. Identity must stay
  // stable — the chat page's loadChat depends on it, and an unstable dep there
  // refetches history mid-send. See the inFlight note above.
  const resumeBeat = useCallback(
    (beat: { text: string; serverId?: string; bubbleId: number; isPiece: boolean }) => {
      if (beat.serverId) {
        lastBeat.current = { serverId: beat.serverId, bubbleId: beat.bubbleId };
      }
      if (beat.isPiece) void loadChips(beat.text);
      else setChips([]);
    },
    [loadChips],
  );

  // Tap a reaction chip. A regenerate drops the prior beat from canon (it stays
  // visible in the full stream) before generating its replacement.
  const sendChip = useCallback(async (chip: Chip) => {
    setChips([]);
    if (chip.kind === "regenerate" && lastBeat.current) {
      const { serverId, bubbleId } = lastBeat.current;
      // The new take replaces this bubble in place (see submitMessage). The backend
      // still drops the prior turn from canon when it sees regenerate_of, so the
      // superseded take remains recoverable server-side — it just isn't left sitting
      // above its own replacement in the transcript.
      await submitMessage(chip.instruction, {
        regenerateOf: serverId,
        replaceBubbleId: bubbleId,
        continuePiece: true,
      });
      return;
    }
    await submitMessage(chip.instruction, { continuePiece: true });
  }, [submitMessage]);

  // Standalone retry on a specific AI beat — the same supersede-in-place path as
  // the regenerate chip, but reachable on any message and STEERABLE: the note is
  // the instruction, so "shorter, less abstract" actually redirects the new take
  // instead of rerolling the same prompt and hoping. A blank note just rerolls.
  const retryMessage = useCallback(
    async (msg: Message, note?: string) => {
      if (!msg.serverId) return;
      const steer = note?.trim();
      await submitMessage(
        steer
          ? `Rewrite your previous response. What to change: ${steer}`
          : "Rewrite your previous response — a different take on the same beat.",
        {
          regenerateOf: msg.serverId,
          replaceBubbleId: msg.id,
          // Retrying a piece must stay a piece; retrying a conversational reply
          // must not become one. Chips exist only for pieces, so their presence
          // is the test.
          continuePiece: chips.length > 0,
        },
      );
    },
    [submitMessage, chips.length],
  );

  // Per-message check/x feedback (B3). Optimistically marks the bubble, then POSTs
  // to the feedback endpoint (which credits/discredits the generation's inputs).
  const sendFeedback = useCallback(
    async (msg: Message, reaction: "check" | "x", note?: string) => {
      if (!msg.serverId) return;
      setMessages(prev =>
        prev.map(m => (m.id === msg.id ? { ...m, feedback: reaction } : m))
      );
      try {
        await apiClient(
          `${process.env.NEXT_PUBLIC_API_URL}/api/v1/messages/${msg.serverId}/feedback`,
          { data: { reaction, note: note ?? null } },
        );
      } catch (err: any) {
        showToast(err.message || "Couldn't save feedback", "error");
      }
    },
    [showToast],
  );

  // Fork an analytic ("why did that land?") chat sharing the same graph.
  // Returns the new conversation id for the caller to navigate to.
  const branchHere = useCallback(async (): Promise<string | null> => {
    try {
      const res = await apiClient<{ conversation_id: string }>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/conversations`,
        { data: { session_type: "analytic", parent_conversation_id: conversationId } },
      );
      return res.conversation_id;
    } catch (err: any) {
      showToast(err.message || "Could not branch", "error");
      return null;
    }
  }, [conversationId, showToast]);

  // Save this conversation into the Library. A story is a DERIVED
  // view over the conversation's canon turns (the backend never copies content),
  // so this is idempotent per conversation — re-saving updates the same story.
  // Returns the story id on success.
  const saveToLibrary = useCallback(async (): Promise<string | null> => {
    try {
      // Title from the first substantial piece (skip short greetings/replies);
      // fall back to the user's opening line, then to nothing (backend defaults).
      const firstPiece =
        messages.find(m => m.sender === "ai" && m.text.length > 200) ||
        messages.find(m => m.sender === "user" && m.text);
      const title = firstPiece
        ? firstPiece.text.slice(0, 48).replace(/\s+\S*$/, "") + "…"
        : undefined;
      const res = await apiClient<{ id: string }>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/stories`,
        { data: { source_conversation_id: conversationId, title } },
      );
      showToast("Saved to Library", "success");
      return res.id;
    } catch (err: any) {
      showToast(err.message || "Could not save to Library", "error");
      return null;
    }
  }, [conversationId, messages, showToast]);

  // Form submit handler — pulls the input value and delegates. Mid-piece, an
  // empty submit means "keep going" (the engine advances with its default).
  // Chips exist only for a piece, so their presence is the register test — an
  // empty submit in ordinary conversation stays a no-op.
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text) {
      if (chips.length > 0 && !isLoading) await submitMessage("Keep going.");
      return;
    }
    setInputValue("");
    await submitMessage(text);
  };

  const copyToClipboard = (id: number, text: string) => {
    navigator.clipboard.writeText(text);
    showToast("Copied to clipboard", "info");
  };

  const editMessage = (id: number, newText: string) =>
    setMessages(prev => prev.map(m => (m.id === id ? { ...m, text: newText } : m)));

  const deleteMessage = (id: number) =>
    setMessages(prev => prev.filter(m => m.id !== id));

  const voteMessage = (id: number, vote: "up" | "down") =>
    setMessages(prev => prev.map(m => (m.id === id ? { ...m, vote: m.vote === vote ? null : vote } : m)));

  return {
    messages,
    setMessages,
    inputValue,
    setInputValue,
    isLoading,
    warming,
    chips,
    sendChip,
    resumeBeat,
    retryMessage,
    branchHere,
    saveToLibrary,
    sendFeedback,
    messagesEndRef,
    submitMessage,
    handleSendMessage,
    copyToClipboard,
    editMessage,
    deleteMessage,
    voteMessage,
  };
}
