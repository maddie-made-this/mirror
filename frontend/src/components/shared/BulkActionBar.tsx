"use client";

import { TrashIcon } from "@/components/ui/Icons";

export function BulkActionBar({
  selectedCount, 
  onPin, 
  onArchive, 
  onDelete, 
  onRestore, 
  onSelectAllUnpinned, 
  allUnpinnedSelected, 
  isArchive, 
  hasUnpinned,
  hidePin
}: any) {
  return (
    <div className="fixed bottom-8 sm:bottom-18 inset-x-4 sm:inset-x-auto sm:left-1/2 sm:-translate-x-1/2 bg-[var(--surface)] border border-[var(--border)] shadow-2xl rounded-2xl p-4 flex items-center justify-between z-50 animate-in slide-in-from-bottom-10 w-auto min-w-[300px]">
      <span className="text-sm font-bold text-[var(--foreground)] whitespace-nowrap mr-4">{selectedCount} Selected</span>
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
        {!isArchive && hasUnpinned && !hidePin && (
           <button 
             onClick={onSelectAllUnpinned}
             className="px-3 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:bg-[var(--surface)] transition-all whitespace-nowrap shrink-0"
           >
             {allUnpinnedSelected ? "Deselect Unpinned" : "Select All"}
           </button>
        )}
        
        {isArchive ? (
          <button 
            onClick={onRestore} disabled={selectedCount === 0}
            className="px-4 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:bg-[var(--surface)] disabled:opacity-50 transition-all whitespace-nowrap"
          >
            Restore
          </button>
        ) : (
          <>
            {!hidePin && (
              <button 
                onClick={onPin} disabled={selectedCount === 0}
                className="px-3 py-2 text-sm font-semibold text-[var(--foreground)] bg-[var(--background)] border border-[var(--border)] rounded-lg hover:bg-[var(--surface)] disabled:opacity-50 transition-all shrink-0"
              >
                Pin
              </button>
            )}
            <button 
              onClick={onArchive} disabled={selectedCount === 0}
              className="px-3 py-2 text-sm font-semibold text-[var(--primary-fg)] bg-[var(--primary)] rounded-lg hover:brightness-90 disabled:opacity-50 transition-all shrink-0"
            >
              Archive
            </button>
          </>
        )}
        <button 
          onClick={onDelete} disabled={selectedCount === 0}
          className="p-2 text-[var(--surface)] bg-red-500 rounded-lg hover:brightness-90 disabled:opacity-50 transition-all shrink-0"
        >
          <TrashIcon className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}