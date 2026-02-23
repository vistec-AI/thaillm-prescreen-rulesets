"use client";

import React, { createContext, useContext, useState, useCallback, useRef } from "react";
import type { ConstantsResponse, ValidateResult } from "../types";
import { fetchConstants } from "../api/constants";
import { runValidation, fetchVersion } from "../api/validation";

// ── Tab identifiers (in display order) ──────────────────────────────
export type TabId = "demographic" | "er" | "graph" | "simulator";

interface AppState {
  /** Currently active tab. */
  activeTab: TabId;
  setActiveTab: (t: TabId) => void;

  /** Loading overlay. */
  overlayText: string | null;
  showOverlay: (text: string) => void;
  hideOverlay: () => void;

  /** Cached constants (severity levels, departments). */
  constants: ConstantsResponse | null;
  loadConstants: () => Promise<ConstantsResponse>;

  /** Validation state. */
  validation: ValidateResult | null;
  validationLoading: boolean;
  triggerValidation: () => Promise<void>;

  /** Last known YAML version hash — used by version polling. */
  version: string | null;
  setVersion: (v: string | null) => void;

  /** Increment to force tab data reload (set by version poll). */
  reloadKey: number;
  triggerReload: () => void;

  /** Whether any editor is open (suppresses auto-reload). */
  isEditing: boolean;
  setIsEditing: (v: boolean) => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [activeTab, setActiveTab] = useState<TabId>("demographic");
  const [overlayText, setOverlayText] = useState<string | null>(null);
  const [constants, setConstants] = useState<ConstantsResponse | null>(null);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [isEditing, setIsEditing] = useState(false);

  // Use ref to avoid stale closures in the constants loader
  const constantsRef = useRef(constants);
  constantsRef.current = constants;

  const showOverlay = useCallback((text: string) => setOverlayText(text), []);
  const hideOverlay = useCallback(() => setOverlayText(null), []);
  const triggerReload = useCallback(() => setReloadKey((k) => k + 1), []);

  const loadConstants = useCallback(async () => {
    if (constantsRef.current) return constantsRef.current;
    const c = await fetchConstants();
    setConstants(c);
    constantsRef.current = c;
    return c;
  }, []);

  const triggerValidation = useCallback(async () => {
    setValidationLoading(true);
    try {
      const res = await runValidation();
      setValidation(res);
    } catch {
      setValidation({ ok: false, stdout: "", stderr: "Failed to reach server" });
    } finally {
      setValidationLoading(false);
    }
  }, []);

  return (
    <AppContext.Provider
      value={{
        activeTab,
        setActiveTab,
        overlayText,
        showOverlay,
        hideOverlay,
        constants,
        loadConstants,
        validation,
        validationLoading,
        triggerValidation,
        version,
        setVersion,
        reloadKey,
        triggerReload,
        isEditing,
        setIsEditing,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

/**
 * Initialize version tracking on mount and start polling every 2 s.
 * Returns a cleanup function to stop the interval.
 */
export function useVersionPolling() {
  const { version, setVersion, isEditing, triggerReload, triggerValidation } = useApp();
  const versionRef = useRef(version);
  versionRef.current = version;
  const editingRef = useRef(isEditing);
  editingRef.current = isEditing;

  React.useEffect(() => {
    let mounted = true;

    const poll = async () => {
      try {
        const res = await fetchVersion();
        if (!mounted) return;
        if (versionRef.current && res.version !== versionRef.current && !editingRef.current) {
          triggerReload();
          triggerValidation();
        }
        setVersion(res.version);
        versionRef.current = res.version;
      } catch {
        // ignore network errors
      }
    };

    // Initial fetch
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [setVersion, triggerReload, triggerValidation]);
}
