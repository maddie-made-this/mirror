"use client";

import { BaseModal } from "@/components/ui/BaseModal";
import { AlertTriangleIcon } from "@/components/ui/Icons";
import { useUser } from "@/context/UserContext";

export function WipeModal({ onConfirm, onClose }: any) {
  const { setHasCompletedOnboarding } = useUser();

  const handleConfirm = () => {
    setHasCompletedOnboarding(false);
    onConfirm();
  };

  return (
    <BaseModal onClose={onClose} maxWidth="md">
      <div className="p-6">
        <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center border border-red-500/20 mb-4"><AlertTriangleIcon className="w-6 h-6 text-red-500" /></div>
        <h3 className="text-xl font-bold text-[var(--foreground)] mb-2">Reset your model?</h3>
        <p className="text-sm text-[var(--muted)] mb-6">This permanently erases everything Mirror has inferred about you — every concept, connection, and reading, plus their embeddings. Your conversations and account are kept, and the model rebuilds as you talk. This <strong>cannot</strong> be undone.</p>
        <div className="flex items-center justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:brightness-95 transition-all">Cancel</button>
          <button onClick={handleConfirm} className="px-4 py-2 text-sm font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 transition-all shadow-sm">Yes, Reset My Model</button>
        </div>
      </div>
    </BaseModal>
  );
}

export function PauseModal({ onConfirm, onClose }: any) {
  return (
    <BaseModal onClose={onClose} maxWidth="md">
      <div className="p-6">
        <h3 className="text-xl font-bold text-[var(--foreground)] mb-2">Pause Memory Extraction?</h3>
        <p className="text-sm text-[var(--muted)] mb-6">If you pause extraction, the AI will stop analyzing your conversations for new traits. It will no longer organically learn about you until you resume collection.</p>
        <div className="flex items-center justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:brightness-95 transition-all">Cancel</button>
          <button onClick={onConfirm} className="px-4 py-2 text-sm font-semibold text-[var(--primary-fg)] bg-[var(--primary)] rounded-lg hover:brightness-90 transition-all shadow-sm">Pause Extraction</button>
        </div>
      </div>
    </BaseModal>
  );
}