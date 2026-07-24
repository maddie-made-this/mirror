import { Dispatch, SetStateAction } from "react";
import { BaseModal } from "@/components/ui/BaseModal"; // Ensure path matches where you saved it

export function SettingSelectButton({ label, description, value, onClick, icon: Icon }: { label: string, description: string, value: string, onClick: () => void, icon?: React.ElementType }) {
  // Left-aligned: the control sits beside its label rather than being pushed to
  // the far edge, which left a wide dead gap on desktop.
  return (
    <div className="flex flex-col sm:flex-row sm:items-center py-2 gap-4 sm:gap-8">
      {/* Icon centered to the left of both title and description */}
      <div className="flex items-center gap-4 sm:min-w-[260px]">
        {Icon && (
          <div className="shrink-0">
            <Icon className="w-5 h-5 text-[var(--foreground)]" />
          </div>
        )}
        <div className="flex flex-col">
          {/* Increased font size to text-base */}
          <h3 className="text-base font-semibold text-[var(--foreground)] transition-colors duration-500">{label}</h3>
          <p className="text-xs text-[var(--muted)] mt-1 transition-colors duration-500">{description}</p>
        </div>
      </div>
      
      <button 
        type="button"
        onClick={onClick}
        className="flex items-center justify-between w-full sm:w-auto min-w-[200px] max-w-full sm:max-w-[260px] p-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg hover:border-[var(--primary)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all text-left duration-500 shrink-0"
      >
        <span className="truncate px-2 text-[var(--foreground)] font-medium text-sm transition-colors duration-500">
          {value}
        </span>
        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-[var(--muted)] shrink-0 transition-colors duration-500" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      </button>
    </div>
  );
} 

// Inside SettingsComponents.tsx, update the SettingsInput definition:
export function SettingsInput({ 
  id, label, value, onChange, onBlur, placeholder, maxLength, errorMsg, icon: Icon 
}: { 
  id: string, label: string, value: string, onChange: (val: string) => void, onBlur?: () => void, placeholder: string, maxLength: number, errorMsg: string, icon?: React.ElementType 
}) {
  const isEmpty = !value.trim();
  const isMaxed = value.length === maxLength;

  return (
    <div className="flex flex-col gap-2 relative">
      <label htmlFor={id} className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)] transition-colors duration-500">
        {Icon && <Icon className="w-5 h-5 text-[var(--foreground)]" />}
        {label} <span className="text-red-500">*</span>
      </label>
      <input 
        type="text" id={id} value={value} maxLength={maxLength} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        className={`w-full p-3 border rounded-lg text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all duration-500 ${isEmpty ? 'border-[var(--border)] bg-red-500/10' : 'border-[var(--border)] bg-[var(--surface)]'}`}
      />
      <div className="flex justify-between items-start text-xs mt-1 min-h-[16px]">
        <span className="text-red-500 font-medium">{isEmpty ? errorMsg : ""}</span>
        <span className={`transition-colors duration-300 ${isMaxed ? 'text-[var(--primary)] font-bold' : 'text-[var(--muted)]'}`}>{value.length}/{maxLength}</span>
      </div>
    </div>
  );
}