"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  ThemeIcon, EnterKeyIcon, CpuIcon
} from "@/components/ui/Icons";
import { DeleteAccountModal } from "@/components/features/settings/SettingsModals";
import { WipeModal, PauseModal } from "@/components/features/memory/MemoryModals";
import { SettingSelectButton, SettingsInput } from "@/components/features/settings/SettingsComponents";
import { ModelPickerModal, type ModelChoice } from "@/components/features/settings/ModelPickerModal";
import { useTheme } from "@/context/ThemeContext";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import { updateProfileData, uploadAvatar, updateSettings } from "@/app/actions/auth";
import { apiClient } from "@/utils/apiClient";
import { dict } from "@/config";

export default function SettingsPage() {
  const { selectedTheme, openThemeModal } = useTheme();
  const { avatar, setAvatar, fullName, setFullName,
    performLogOut, isSignedIn, settings, updateLocalSetting, userId
  } = useUser();
  const { showToast } = useToast();

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showPauseModal, setShowPauseModal] = useState(false);
  const [showWipeModal, setShowWipeModal] = useState(false);

  const [showModelPicker, setShowModelPicker] = useState(false);
  const [modelChoices, setModelChoices] = useState<ModelChoice[]>([]);

  // The catalogue is server-owned (GET /account/models) so the picker can only
  // ever offer ids the backend will accept.
  useEffect(() => {
    apiClient<{ models: ModelChoice[] }>(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/account/models`,
    )
      .then((r) => setModelChoices(r?.models ?? []))
      .catch(() => setModelChoices([]));
  }, []);

  // settings.selectedModel stores the ID; show the human label when we know it.
  const currentModelLabel =
    modelChoices.find((m) => m.id === settings.selectedModel)?.label ??
    (settings.selectedModel || "Default");

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const objectUrl = URL.createObjectURL(file);
      setAvatar(objectUrl);
      if (isSignedIn) {
        const formData = new FormData();
        formData.append("avatar", file);
        const { avatarUrl, error } = await uploadAvatar(formData);
        if (error) showToast(error, "error");
        else if (avatarUrl) setAvatar(avatarUrl);
      }
    }
  };

  const handleWipeModel = async () => {
    // Server-side model reset: Neo4j subgraph + Qdrant vectors. Chats, feedback,
    // and the account survive; the graph rebuilds from future conversation.
    setShowWipeModal(false);
    try {
      const res = await apiClient<{ wiped: boolean; stores: Record<string, string> }>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/account/wipe-model`,
        { data: { confirm: "WIPE" } },
      );
      if (res.wiped) {
        showToast("Model erased. It rebuilds as you talk.", "success");
      } else {
        showToast("Partial wipe — try again to finish.", "error");
      }
      // Any open map/understanding view should drop the old graph immediately.
      window.dispatchEvent(new CustomEvent("graphUpdated"));
    } catch {
      showToast("Wipe failed — nothing was deleted.", "error");
    }
  };

  const handleDownload = async () => {
    // The whole model, as the README promises: the graph (nodes, edges,
    // clusters, interpretations), the understanding list, and the verbatim
    // episodic record. One bundle, so nothing the system believes about the
    // user is outside the file.
    if (!userId) {
      showToast("Sign in to export your model.", "error");
      return;
    }
    try {
      const base = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}`;
      const [graph, understanding] = await Promise.all([
        apiClient<unknown>(`${base}?limit=2000&include_cooccurrence=true`),
        apiClient<unknown[]>(`${base}/understanding?limit=300`),
      ]);
      const memories: unknown[] = [];
      for (let offset = 0; offset < 5000; offset += 200) {
        const page = await apiClient<unknown[]>(
          `${base}/mentions?limit=200&offset=${offset}`,
        );
        memories.push(...page);
        if (page.length < 200) break;
      }
      const bundle = {
        format: "mirror-export",
        version: 1,
        exported_at: new Date().toISOString(),
        graph,
        understanding,
        memories,
      };
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `mirror_export_${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showToast(`Exported your model (${memories.length} memory records).`, "success");
    } catch {
      showToast("Export failed — please try again.", "error");
    }
  };

  const toggleMemoryPause = async () => {
    if (!settings.memoryPaused) {
      setShowPauseModal(true);
    } else {
      updateLocalSetting("memoryPaused", false);
      showToast("Memory extraction resumed.", "success");
      if (isSignedIn) await updateSettings({ memory_paused: false });
    }
  };

  const handleNameBlur = async () => {
    let finalName = fullName.trim();
    if (!finalName) {
      finalName = "User";
      setFullName("User");
    }
    if (isSignedIn) await updateProfileData(finalName);
  };

  return (
    <div className="flex-1 w-full flex flex-col bg-transparent p-3 sm:p-6 lg:p-8 transition-colors duration-500 overflow-x-hidden">

      {showWipeModal && (
        <WipeModal onConfirm={handleWipeModel} onClose={() => setShowWipeModal(false)} />
      )}
      {showPauseModal && (
        <PauseModal
          onConfirm={async () => {
            updateLocalSetting("memoryPaused", true);
            if (isSignedIn) await updateSettings({ memory_paused: true });
            setShowPauseModal(false);
            showToast("Memory collection paused.", "info");
          }}
          onClose={() => setShowPauseModal(false)}
        />
      )}

      <div className="w-full max-w-3xl mx-auto bg-[var(--surface)] rounded-2xl shadow-sm border border-[var(--border)] p-5 sm:p-10 mb-12 transition-colors duration-500">

        <h2 className="text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-balance mb-8 border-b border-[var(--border)] pb-4 transition-colors duration-500">Profile Settings</h2>

        {/* The avatar stays centred — it is the page's focal element, not a row.
            Everything BELOW it (the profile fields and the setting rows) is
            left-aligned; only this block is centred. */}
        <div className="flex flex-col items-center mb-10">

          {/* Avatar */}
          <div className="relative w-48 h-48 sm:w-56 sm:h-56 group">
            <div
              onClick={() => fileInputRef.current?.click()}
              className="w-full h-full rounded-full bg-[var(--background)] border-2 border-dashed border-[var(--border)] flex items-center justify-center cursor-pointer hover:brightness-95 transition-all relative overflow-hidden duration-500 shadow-sm"
            >
              {avatar ? (
                <img src={avatar} alt="Avatar Preview" className="w-full h-full object-cover" />
              ) : (
                /* Initial from the display name — reads as a real avatar rather
                   than a broken/cropped upload affordance. Falls back to a
                   neutral glyph so it is never blank. */
                <span className="select-none font-bold text-[var(--muted)] group-hover:text-[var(--foreground)] transition-colors duration-500 text-7xl sm:text-8xl leading-none">
                  {(fullName?.trim() || "?").charAt(0).toUpperCase()}
                </span>
              )}
              <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                <span className="text-white text-sm font-semibold">Upload Image</span>
              </div>
            </div>
            {avatar && (
              <button
                type="button"
                onClick={async (e) => {
                  e.stopPropagation();
                  setAvatar(null);
                  if (fileInputRef.current) fileInputRef.current.value = "";
                  if (isSignedIn) await updateProfileData(fullName, null);
                }}
                className="absolute top-2 right-2 sm:top-4 sm:right-4 bg-red-600 text-white rounded-full p-1.5 shadow-lg hover:bg-red-700 hover:scale-110 transition-all z-10 border border-red-800"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
          <p className="text-sm text-[var(--muted)] mt-4 transition-colors duration-500">Click to upload avatar</p>
          <input type="file" hidden ref={fileInputRef} onChange={handleImageUpload} accept="image/*" />

          {/* Profile fields */}
          <div className="flex flex-col gap-6 w-full mt-6">
            <SettingsInput id="fullName" label="Display Name" value={fullName} onChange={setFullName} onBlur={handleNameBlur} placeholder="Enter the name the AI will use for you" maxLength={20} errorMsg="Display Name cannot be empty." />
          </div>

          <hr className="border-[var(--border)] my-6 w-full transition-colors duration-500" />

          {/* App settings */}
          <SettingSelectButton
            label="Response Model"
            description="Which model writes the replies."
            value={currentModelLabel}
            onClick={() => setShowModelPicker(true)}
            icon={CpuIcon}
          />
          <SettingSelectButton label="Site Theme" description="Customize the interface appearance and colors." value={selectedTheme} onClick={openThemeModal} icon={ThemeIcon} />

          <hr className="border-[var(--border)] my-4 w-full transition-colors duration-500" />

          {/* Chat Settings */}
          <h2 className="text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-balance mb-2 border-b border-[var(--border)] pb-4 mt-4 w-full transition-colors duration-500">Chat Settings</h2>

          {/* The description swaps between two different-length sentences as the
              toggle flips. flex-1 (with min-w-0 so long text wraps instead of
              widening the row) makes the text absorb that change, pinning the
              toggle to the right edge — otherwise the block sizes to its content
              and the toggle jumps sideways on every flip. */}
          <div className="flex items-center py-2 gap-4 sm:gap-8 w-full">
            <div className="flex items-center gap-4 flex-1 min-w-0 sm:min-w-[260px]">
              <div className="shrink-0">
                <EnterKeyIcon className="w-5 h-5 text-[var(--foreground)]" />
              </div>
              <div className="flex flex-col">
                <h3 className="text-base font-semibold text-[var(--foreground)] transition-colors duration-500">Enter to Send</h3>
                <p className="text-xs text-[var(--muted)] mt-1 transition-colors duration-500">
                  {settings.enterToSend
                    ? "Enter sends your message. Use Shift+Enter for a new line."
                    : "Enter creates a new line. Use Shift+Enter or the Send button to submit."}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={async () => {
                const next = !settings.enterToSend;
                updateLocalSetting("enterToSend", next);
                if (isSignedIn) await updateSettings({ enter_to_send: next });
              }}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-500 ease-in-out focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--surface)] ${settings.enterToSend ? 'bg-[var(--primary)]' : 'bg-[var(--border)]'}`}
            >
              <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-500 ease-in-out ${settings.enterToSend ? 'translate-x-5' : 'translate-x-0'}`} />
            </button>
          </div>

          <hr className="border-[var(--border)] my-4 w-full transition-colors duration-500" />

          {/* Advanced Options */}
          <div className="flex flex-col border border-[var(--border)] rounded-lg overflow-hidden transition-colors duration-500 w-full">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center justify-between w-full p-4 bg-[var(--background)] hover:brightness-95 transition-all text-left duration-500"
            >
              <span className="text-base font-semibold text-[var(--foreground)]">Advanced Options</span>
              <svg xmlns="http://www.w3.org/2000/svg" className={`h-5 w-5 text-[var(--muted)] transition-transform duration-300 ${showAdvanced ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
            <div className={`transition-all duration-300 ease-in-out overflow-hidden ${showAdvanced ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'}`}>
              <div className="p-4 bg-[var(--surface)] border-t border-[var(--border)] flex flex-col gap-3 transition-colors duration-500">

                {/* Memory pause */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border border-[var(--border)] rounded-lg bg-[var(--background)]">
                  <div>
                    <h4 className="text-sm font-bold text-[var(--foreground)]">
                      {!settings.memoryPaused ? "Pause Memory Extraction" : "Restart Memory Extraction"}
                    </h4>
                    <p className="text-xs text-[var(--muted)] mt-1">
                      {!settings.memoryPaused
                        ? "Temporarily stop AI from learning new traits from your conversations."
                        : "Re-enable AI learning new traits from your conversations."}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={toggleMemoryPause}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-500 ease-in-out focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-2 focus:ring-offset-[var(--background)] ${!settings.memoryPaused ? 'bg-[var(--primary)]' : 'bg-[var(--border)]'}`}
                  >
                    <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-500 ease-in-out ${!settings.memoryPaused ? 'translate-x-5' : 'translate-x-0'}`} />
                  </button>
                </div>

                {/* Export */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border border-[var(--border)] rounded-lg bg-[var(--background)]">
                  <div>
                    <h4 className="text-sm font-bold text-[var(--foreground)]">Export Your Model</h4>
                    <p className="text-xs text-[var(--muted)] mt-1">Download everything as JSON — concepts, connections, readings, and the verbatim record.</p>
                  </div>
                  <button type="button" onClick={handleDownload} className="shrink-0 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] text-sm font-semibold rounded-lg hover:brightness-95 transition-colors">Export JSON</button>
                </div>

                {/* Sign out */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border border-[var(--border)] rounded-lg bg-[var(--background)]">
                  <div>
                    <h4 className="text-sm font-bold text-[var(--foreground)]">Sign Out</h4>
                    <p className="text-xs text-[var(--muted)] mt-1">Securely end your session and clear local browser data.</p>
                  </div>
                  <button type="button" onClick={() => performLogOut()} className="shrink-0 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] text-sm font-semibold rounded-lg hover:brightness-95 transition-colors">Sign Out</button>
                </div>

                {/* Reset model — wipes the graph (Neo4j) and its vectors (Qdrant)
                    server-side; chats and the account survive. This control once
                    only cleared a retired localStorage key while claiming to wipe
                    everything — it now does exactly what it says or it wouldn't
                    be here. */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border border-red-500/20 bg-red-500/5 rounded-lg">
                  <div>
                    <h4 className="text-sm font-bold text-red-500">Reset Your Model</h4>
                    <p className="text-xs text-red-500/70 mt-1">Erase every concept, connection, and reading. Your chats and account are kept; the model rebuilds as you talk.</p>
                  </div>
                  <button type="button" onClick={() => setShowWipeModal(true)} className="shrink-0 px-4 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 transition-colors">Reset Model</button>
                </div>

                {/* Delete account */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-4 border border-red-500/20 bg-red-500/5 rounded-lg">
                  <div>
                    <h4 className="text-sm font-bold text-red-500">Delete Account</h4>
                    <p className="text-xs text-red-500/70 mt-1">Permanently delete your account and all data.</p>
                  </div>
                  <button type="button" onClick={() => setShowDeleteModal(true)} className="shrink-0 px-4 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 transition-colors">Delete Account</button>
                </div>

              </div>
            </div>
          </div>

        </div>
      </div>

      {showModelPicker && (
        <ModelPickerModal
          models={modelChoices}
          selectedId={settings.selectedModel}
          onSelect={async (id) => {
            updateLocalSetting("selectedModel", id);
            if (isSignedIn) await updateSettings({ preferred_model: id });
            showToast("Response model updated.", "success");
          }}
          onClose={() => setShowModelPicker(false)}
        />
      )}

      {showDeleteModal && <DeleteAccountModal onClose={() => setShowDeleteModal(false)} onDeleted={performLogOut} />}
    </div>
  );
}
