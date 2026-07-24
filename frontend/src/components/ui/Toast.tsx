"use client";

export function Toast({ message, type = "success" }: { message: string | null, type?: "success" | "error" | "info" }) {
  if (!message) return null;

  // Determine the color of the little dot based on the type of notification
  let dotColor = "bg-[var(--primary)]";
  if (type === "error") dotColor = "bg-red-500";
  if (type === "info") dotColor = "bg-blue-500";

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] bg-[var(--surface)] border border-[var(--border)] px-4 py-2.5 rounded-lg shadow-xl text-[var(--foreground)] text-sm font-semibold flex items-center gap-2 animate-in slide-in-from-bottom-5 fade-in duration-300">
      <div className={`w-2 h-2 rounded-full ${dotColor}`}></div>
      {message}
    </div>
  );
}