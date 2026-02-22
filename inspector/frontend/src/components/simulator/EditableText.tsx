"use client";

import { useState, useRef, useEffect } from "react";

interface EditableTextProps {
  /** The text to display */
  text: string;
  /** Called when the user finishes editing */
  onSave: (newText: string) => void;
  /** HTML tag to render (defaults to "span") */
  as?: "span" | "p" | "h3" | "h4" | "label";
  /** Extra CSS class names */
  className?: string;
}

/**
 * Inline-editable text component.
 * Shows text with a pencil icon on hover. Clicking enters edit mode
 * (input field). Blur or Enter saves the new text.
 */
export default function EditableText({
  text,
  onSave,
  as: Tag = "span",
  className = "",
}: EditableTextProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const inputRef = useRef<HTMLInputElement>(null);

  // Sync draft when text prop changes externally
  useEffect(() => {
    if (!editing) setDraft(text);
  }, [text, editing]);

  // Auto-focus input when entering edit mode
  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft.trim() !== text) {
      onSave(draft.trim());
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(text);
            setEditing(false);
          }
        }}
        className={`border border-blue-400 rounded px-1 py-0.5 text-sm outline-none focus:ring-1 focus:ring-blue-400 w-full ${className}`}
      />
    );
  }

  return (
    <Tag
      className={`group inline-flex items-center gap-1 cursor-pointer hover:bg-blue-50 rounded px-0.5 transition-colors ${className}`}
      onClick={() => setEditing(true)}
      title="Click to edit"
    >
      {text}
      <svg
        className="w-3 h-3 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
        />
      </svg>
    </Tag>
  );
}
