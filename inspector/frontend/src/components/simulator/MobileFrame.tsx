"use client";

import type { ReactNode } from "react";

/**
 * iPhone-shaped frame for previewing how the simulator UI looks on mobile.
 * Uses iPhone 14 logical dimensions (393 x 852 CSS pixels) with a
 * visual bezel, notch, and home indicator to approximate the real device.
 *
 * When `active` is false the decorative chrome is hidden and size constraints
 * are removed, but the DOM tree structure stays identical so that React
 * preserves the component instances (and therefore local state) of children
 * when the user toggles between desktop and mobile views.
 */

/* iPhone 14 logical viewport */
const SCREEN_W = 393;
const SCREEN_H = 852;

interface MobileFrameProps {
  children: ReactNode;
  /** When false, chrome is hidden and content renders without size constraints. */
  active?: boolean;
}

export default function MobileFrame({ children, active = true }: MobileFrameProps) {
  return (
    <div className={active ? "flex justify-center py-4" : ""}>
      {/* Device bezel */}
      <div
        className={`relative ${active ? "bg-gray-900 rounded-[3rem] shadow-2xl" : ""}`}
        style={active ? { width: SCREEN_W + 24, padding: "12px" } : undefined}
      >
        {/* Dynamic Island / notch */}
        <div
          className={`absolute top-3 left-1/2 -translate-x-1/2 w-28 h-7 bg-gray-900 rounded-full z-10 ${active ? "" : "hidden"}`}
        />

        {/* Screen area */}
        <div
          className={`relative ${active ? "bg-white rounded-[2.4rem] overflow-hidden" : ""}`}
          style={active ? { width: SCREEN_W, height: SCREEN_H } : undefined}
        >
          {/* Status bar (time, signal, battery) — decorative */}
          <div
            className={`sticky top-0 z-10 flex items-center justify-between px-8 pt-4 pb-1 bg-white/90 backdrop-blur-sm text-xs font-semibold text-gray-800 ${active ? "" : "hidden"}`}
          >
            <span>9:41</span>
            <div className="flex items-center gap-1">
              {/* signal bars */}
              <svg width="16" height="12" viewBox="0 0 16 12" fill="currentColor">
                <rect x="0" y="8" width="3" height="4" rx="0.5" />
                <rect x="4.5" y="5" width="3" height="7" rx="0.5" />
                <rect x="9" y="2" width="3" height="10" rx="0.5" />
                <rect x="13.5" y="0" width="3" height="12" rx="0.5" opacity="0.3" />
              </svg>
              {/* wifi */}
              <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor">
                <path d="M7 10.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3z" />
                <path d="M3.5 8.5a5 5 0 017 0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M1 5.5a8 8 0 0112 0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              {/* battery */}
              <svg width="24" height="12" viewBox="0 0 24 12" fill="currentColor">
                <rect x="0" y="1" width="20" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1" />
                <rect x="1.5" y="2.5" width="14" height="7" rx="1" />
                <rect x="21" y="4" width="2" height="4" rx="0.5" />
              </svg>
            </div>
          </div>

          {/* Scrollable content area — .mobile-preview triggers CSS overrides
              in globals.css so viewport-based Tailwind breakpoints (md:grid-cols-2)
              collapse to single-column inside this narrow container.
              In desktop mode the class is omitted and max-w-2xl constrains width. */}
          <div
            className={active ? "mobile-preview overflow-y-auto px-4 pb-8" : "max-w-2xl"}
            style={active ? { height: SCREEN_H - 48 /* subtract status bar */ } : undefined}
          >
            {children}
          </div>

          {/* Home indicator bar */}
          <div
            className={`absolute bottom-2 left-1/2 -translate-x-1/2 w-32 h-1 bg-gray-800 rounded-full opacity-30 ${active ? "" : "hidden"}`}
          />
        </div>
      </div>
    </div>
  );
}
