"use client";

import { useApp } from "@/lib/context/AppContext";

export default function LoadingOverlay() {
  const { overlayText } = useApp();
  if (!overlayText) return null;

  return (
    <div className="fixed inset-0 bg-white/75 flex items-center justify-center z-[1000]">
      <div className="bg-white border border-gray-200 rounded-md px-4 py-3 shadow-lg text-sm flex items-center gap-3">
        <div className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-gray-600 animate-spin" />
        <span>{overlayText}</span>
      </div>
    </div>
  );
}
