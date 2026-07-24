import { BaseModal } from "@/components/ui/BaseModal";

export function ListModal({ title, items, selectedItem, onSelect, onClose }: { title: string, items: string[], selectedItem: string, onSelect: (val: string) => void, onClose: () => void }) {
  return (
    <BaseModal onClose={onClose} maxWidth="md">
      <div className="flex items-center justify-between p-4 sm:p-6 border-b border-[var(--border)] shrink-0 transition-colors duration-500">
        <h3 className="text-lg font-bold text-[var(--foreground)] transition-colors duration-500">{title}</h3>
        <button onClick={onClose} className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] bg-[var(--background)] hover:brightness-95 rounded-full transition-colors duration-500">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" /></svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-2">
        {items.map((item) => (
          <button 
            key={item} 
            onClick={() => { onSelect(item); onClose(); }}
            className={`w-full text-left px-4 py-3 rounded-lg border transition-all duration-500 ${selectedItem === item ? 'border-[var(--primary)] bg-[var(--background)] font-semibold text-[var(--foreground)]' : 'border-[var(--border)] hover:border-[var(--muted)] text-[var(--muted)] hover:text-[var(--foreground)]'}`}
          >
            {item}
          </button>
        ))}
      </div>
    </BaseModal>
  );
}