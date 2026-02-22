"use client";

import { useState, useRef, useEffect, useCallback } from "react";

export interface QidOption {
  id: string;
  label: string;
  /** Question type (single_select, multi_select, number_range, etc.) */
  type?: string;
  /** Available options for select-type questions (label is what predicates compare against). */
  options?: Array<{ id?: string; label?: string }>;
  /** For number_range questions. */
  min_value?: number;
  max_value?: number;
  step?: number;
}

interface QidPickerProps {
  value: string;
  onChange: (qid: string) => void;
  availableQids: QidOption[];
  disabled?: boolean;
  placeholder?: string;
}

/**
 * Searchable combobox for selecting a question ID (QID).
 *
 * Shows a text input that doubles as a search filter. On focus or typing,
 * a dropdown appears with matching QIDs (substring match on both QID and
 * question text). Clicking an item sets the value; clicking outside closes
 * the dropdown. Manual typing is still allowed for QIDs not yet in the graph.
 *
 * Falls back to a plain text input when availableQids is empty.
 */
export default function QidPicker({
  value,
  onChange,
  availableQids,
  disabled,
  placeholder = "question_id",
}: QidPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Filter available QIDs by search term (match on both id and label)
  const filtered = useCallback(() => {
    const term = search.toLowerCase();
    if (!term) return availableQids;
    return availableQids.filter(
      (q) =>
        q.id.toLowerCase().includes(term) ||
        q.label.toLowerCase().includes(term),
    );
  }, [search, availableQids]);

  const handleFocus = () => {
    if (availableQids.length > 0) {
      setSearch("");
      setOpen(true);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    onChange(val);
    setSearch(val);
    if (availableQids.length > 0) {
      setOpen(true);
    }
  };

  const handleSelect = (qid: string) => {
    onChange(qid);
    setSearch("");
    setOpen(false);
    inputRef.current?.blur();
  };

  // No dropdown if no QIDs available — plain text input fallback
  if (availableQids.length === 0) {
    return (
      <input
        type="text"
        className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
    );
  }

  const matches = filtered();

  return (
    <div ref={containerRef} className="relative">
      <input
        ref={inputRef}
        type="text"
        className="w-full border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
        value={value}
        onChange={handleInputChange}
        onFocus={handleFocus}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
      />
      {open && matches.length > 0 && (
        <ul className="absolute z-50 left-0 right-0 mt-0.5 max-h-48 overflow-auto bg-white border border-gray-200 rounded shadow-lg text-xs">
          {matches.map((q) => (
            <li
              key={q.id}
              className={`px-2 py-1 cursor-pointer hover:bg-blue-50 flex items-baseline gap-1.5 ${
                q.id === value ? "bg-blue-50 font-semibold" : ""
              }`}
              onMouseDown={(e) => {
                // Prevent input blur before selection registers
                e.preventDefault();
                handleSelect(q.id);
              }}
            >
              <code className="text-[11px] text-blue-700 shrink-0">{q.id}</code>
              <span className="text-gray-500 truncate">{q.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
