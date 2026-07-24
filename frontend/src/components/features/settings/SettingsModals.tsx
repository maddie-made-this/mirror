import { useState } from "react";
import { apiClient } from "@/utils/apiClient";
import { BaseModal } from "@/components/ui/BaseModal";

export function ThemeModal({ selectedTheme, onSelect, onClose, standardThemes, colorGrid }: any) {
  return (
    <BaseModal onClose={onClose} maxWidth="5xl">
      <div className="flex items-center justify-between p-4 sm:p-6 border-b border-[var(--border)] shrink-0 transition-colors duration-500">
        <h3 className="text-lg font-bold text-[var(--foreground)] transition-colors duration-500">Select Site Theme</h3>
        <button onClick={onClose} className="p-1.5 text-[var(--muted)] hover:text-[var(--foreground)] bg-[var(--background)] hover:brightness-95 rounded-full transition-colors duration-500">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-2">
        <div className="mb-6">
          <h4 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-4 transition-colors duration-500">Standard & Accessibility</h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4">
            {standardThemes.map((t: string) => (
              <button 
                key={t} 
                onClick={() => { onSelect(t); onClose(); }}
                className={`flex flex-col gap-2 p-2 rounded-xl border-2 transition-all duration-500 hover:scale-105 ${selectedTheme === t ? 'border-[var(--primary)] bg-[var(--background)]' : 'border-[var(--border)] hover:border-[var(--muted)]'}`}
              >
                <div className="w-full h-16 sm:h-20 rounded-lg border border-[var(--border)] overflow-hidden flex flex-col shadow-sm relative transition-colors duration-500">
                  <div data-theme={t} className="absolute inset-0 flex flex-col bg-[var(--background)]">
                    <div className="h-4 sm:h-5 shrink-0 bg-[var(--header-bg)] border-b-2 border-[var(--header-border)]"></div>
                    <div className="flex flex-1 relative">
                      <div className="w-4 sm:w-6 border-r-2 border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]"></div>
                      <div className="flex-1 bg-[var(--background)]">
                        {t.includes("Protanopia") && <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'repeating-linear-gradient(45deg, #000 25%, transparent 25%, transparent 75%, #000 75%, #000)', backgroundSize: '10px 10px' }}></div>}
                        {t.includes("Deuteranopia") && <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'radial-gradient(#000 2px, transparent 2px)', backgroundSize: '10px 10px' }}></div>}
                      </div>
                    </div>
                  </div>
                </div>
                <span className={`text-[10px] sm:text-xs text-center w-full leading-tight transition-colors duration-500 ${selectedTheme === t ? 'font-bold text-[var(--foreground)]' : 'font-medium text-[var(--muted)]'}`}>{t}</span>
              </button>
            ))}
          </div>
        </div>
        
        <div>
          <h4 className="text-xs font-bold text-[var(--muted)] uppercase tracking-wider mb-4 transition-colors duration-500">Color Palette</h4>
          <div className="w-full pb-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8 gap-4">
            {colorGrid.map((row: string[]) => (
              row.map((themeName) => (
                <button 
                  key={themeName} 
                  onClick={() => { onSelect(themeName); onClose(); }}
                  className={`flex flex-col gap-2 p-2 rounded-xl border-2 transition-all duration-500 hover:scale-105 ${selectedTheme === themeName ? 'border-[var(--primary)] bg-[var(--background)]' : 'border-[var(--border)] hover:border-[var(--muted)]'}`}
                >
                  <div className="w-full h-16 rounded-lg border border-[var(--border)] overflow-hidden flex flex-col shadow-sm relative transition-colors duration-500">
                    <div data-theme={themeName} className="absolute inset-0 flex flex-col bg-[var(--background)]">
                      <div className="h-4 shrink-0 bg-[var(--header-bg)] border-b-2 border-[var(--primary-hover)]"></div>
                      <div className="flex flex-1">
                        <div className="w-4 border-r-2 border-[var(--primary-hover)] bg-[var(--sidebar-bg)]"></div>
                        <div className="flex-1 bg-[var(--background)]"></div>
                      </div>
                    </div>
                  </div>
                  <span className={`text-[10px] sm:text-xs text-center w-full transition-colors duration-500 ${selectedTheme === themeName ? 'font-bold text-[var(--foreground)]' : 'font-medium text-[var(--muted)]'}`}>{themeName}</span>
                </button>
              ))
            ))}
          </div>
        </div>
      </div>
    </BaseModal>
  );
}
/**
 * Irreversible account deletion. The backend (POST /account/delete) requires the
 * literal confirmation phrase "DELETE", so the input isn't decoration — it is the
 * contract, and the button stays disabled until it matches.
 */
export function DeleteAccountModal({ onClose, onDeleted }: { onClose: () => void; onDeleted?: () => void }) {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const handleDelete = async () => {
    setBusy(true);
    setError("");
    try {
      await apiClient(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/account/delete`, {
        data: { confirm },
      });
      onDeleted?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deletion failed. Please try again.");
      setBusy(false);
    }
  };

  return (
    <BaseModal onClose={onClose} maxWidth="sm">
      <div className="p-6 text-center">
        <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto mb-4">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
        </div>
        <h3 className="text-xl font-bold text-[var(--foreground)] mb-2 transition-colors duration-500">Are you sure?</h3>
        <p className="text-sm text-[var(--muted)] mb-4 transition-colors duration-500">This cannot be undone. Your conversations, your graph, and your account will be permanently deleted.</p>
        <label htmlFor="confirm-delete" className="block text-xs text-[var(--muted)] mb-1.5 text-left">Type <span className="font-mono font-bold text-[var(--foreground)]">DELETE</span> to confirm</label>
        <input
          id="confirm-delete"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={busy}
          autoComplete="off"
          className="w-full px-3 py-2 mb-4 rounded-lg bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] font-mono text-sm focus:outline-none focus:ring-2 focus:ring-red-500 transition-colors duration-500"
        />
        {error && <p className="text-sm text-red-500 mb-4">{error}</p>}
        <div className="flex gap-3 justify-center">
          <button onClick={onClose} disabled={busy} className="px-4 py-2 border border-[var(--border)] text-[var(--foreground)] font-semibold rounded-lg hover:bg-[var(--background)] transition-colors duration-500 disabled:opacity-50">Cancel</button>
          <button
            onClick={handleDelete}
            disabled={confirm !== "DELETE" || busy}
            className="px-4 py-2 bg-red-600 text-white font-semibold rounded-lg hover:bg-red-700 transition-colors duration-500 disabled:opacity-40 disabled:hover:bg-red-600"
          >
            {busy ? "Deleting…" : "Delete Account"}
          </button>
        </div>
      </div>
    </BaseModal>
  );
}
