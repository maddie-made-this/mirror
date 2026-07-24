// Client-side story export (product reshape §4.3 / P1.6). Canon → markdown/txt download.
// No backend, no storage — composed from the same canon beats the document renders.
import type { StoryDetail } from "@/types/story";

function _body(story: StoryDetail): string {
  return story.beats.map((b) => b.text.trim()).filter(Boolean).join("\n\n");
}

export function storyToMarkdown(story: StoryDetail): string {
  return `# ${story.title || "Untitled story"}\n\n${_body(story)}\n`;
}

export function storyToText(story: StoryDetail): string {
  return `${story.title || "Untitled story"}\n\n${_body(story)}\n`;
}

function _slug(title: string | null): string {
  return (
    (title || "story")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "story"
  );
}

export function downloadStory(story: StoryDetail, format: "md" | "txt"): void {
  const content = format === "md" ? storyToMarkdown(story) : storyToText(story);
  const mime = format === "md" ? "text/markdown" : "text/plain";
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${_slug(story.title)}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
