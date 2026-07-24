"use client";

import { BaseModal } from "@/components/ui/BaseModal";
import { AlertTriangleIcon } from "@/components/ui/Icons";

export function ConfirmDeleteModal({ title, message, onConfirm, onClose }: any) {
  return (
    <BaseModal onClose={onClose} maxWidth="sm">
      <div className="p-6">
        <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center border border-red-500/20 mb-4">
          <AlertTriangleIcon className="w-6 h-6 text-red-500" />
        </div>
        <h3 className="text-xl font-bold text-[var(--foreground)] mb-2">{title || "Confirm Deletion"}</h3>
        <p className="text-sm text-[var(--muted)] mb-6">{message || "This action cannot be undone."}</p>
        <div className="flex items-center justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:brightness-95 transition-all">Cancel</button>
          <button onClick={onConfirm} className="px-4 py-2 text-sm font-semibold text-white bg-red-500 rounded-lg hover:bg-red-600 transition-all shadow-sm">Delete</button>
        </div>
      </div>
    </BaseModal>
  );
}