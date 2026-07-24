// Story documents (product reshape §2 / P1.1). A story is a DERIVED view over a
// conversation's canon turns — content is never stored on the story row.

export interface StoryBeat {
  turn_id: string;   // the beat's message_id (shared identity with the chat editor)
  text: string;
}

export interface StorySummary {
  id: string;
  source_conversation_id: string;
  title: string | null;
  pinned: boolean;
  cover_state: Record<string, unknown>;
  color_map: StoryColorMap;
  created_at: string | null;
  updated_at: string | null;
}

export interface StoryDetail extends StorySummary {
  beats: StoryBeat[];
}

// stories.color_map (piece tints + speaker colors). Optional/forward-compatible:
// beat_tints maps a beat's turn_id → a CSS color for its piece tint. Empty until the
// (deferred) tint writer populates it.
export interface StoryColorMap {
  beat_tints?: Record<string, string>;
  [k: string]: unknown;
}
