"use client";

import { BaseModal } from "@/components/ui/BaseModal";

export interface ModelChoice {
  id: string;
  label: string;
  blurb: string;
}

/**
 * Response-model picker.
 *
 * Shows the trade-off per model rather than a bare list of slugs — the choice is
 * only meaningful if you can see why you'd pick one. The catalogue is fetched
 * from the backend (GET /account/models), never hardcoded here, so the picker
 * can't offer an id the server would reject.
 */
export function ModelPickerModal({
  models,
  selectedId,
  onSelect,
  onClose,
}: {
  models: ModelChoice[];
  selectedId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <BaseModal onClose={onClose} maxWidth="md">
      <div className="flex items-center justify-between p-4 sm:p-6 border-b border-[var(--border)] shrink-0 transition-colors duration-500">
        <div>
          <h3 className="text-lg font-bold text-[var(--foreground)]">Response model</h3>
          <p className="text-xs text-[var(--muted)] mt-1">
            Which model writes the replies. Analysis and extraction always run on
            their own tiers.
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] bg-[var(--background)] hover:brightness-95 rounded-full transition-colors duration-500 shrink-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-2">
        {models.length === 0 && (
          <p className="text-sm text-[var(--muted)]">
            Could not load the model list. Check that the backend is running.
          </p>
        )}
        {models.map((m) => {
          const active = m.id === selectedId;
          return (
            <button
              key={m.id}
              onClick={() => {
                onSelect(m.id);
                onClose();
              }}
              className={`w-full text-left px-4 py-3 rounded-lg border transition-all duration-500 ${
                active
                  ? "border-[var(--primary)] bg-[var(--background)]"
                  : "border-[var(--border)] hover:border-[var(--muted)]"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span
                  className={`text-sm ${
                    active
                      ? "font-semibold text-[var(--foreground)]"
                      : "text-[var(--foreground)]"
                  }`}
                >
                  {m.label}
                </span>
                {active && (
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--primary)] shrink-0">
                    Current
                  </span>
                )}
              </div>
              <p className="text-xs text-[var(--muted)] mt-1">{m.blurb}</p>
              <p className="text-[10px] text-[var(--muted)] mt-1 font-mono opacity-60">{m.id}</p>
            </button>
          );
        })}
      </div>
    </BaseModal>
  );
}
