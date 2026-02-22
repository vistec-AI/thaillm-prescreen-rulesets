"use client";

import { useApp, type TabId } from "@/lib/context/AppContext";

const TABS: { id: TabId; label: string }[] = [
  { id: "demographic", label: "Demographic" },
  { id: "er", label: "ER Checklist" },
  { id: "graph", label: "OLDCARTS / OPD" },
];

export default function TabBar() {
  const { activeTab, setActiveTab } = useApp();

  return (
    <div className="flex gap-0 border-b-2 border-gray-200 mb-2">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => setActiveTab(tab.id)}
          className={`px-3 py-2 md:px-5 md:py-2 border-none cursor-pointer text-sm font-medium transition-colors -mb-[2px] border-b-2 ${
            activeTab === tab.id
              ? "bg-white text-gray-800 border-b-blue-500 font-semibold"
              : "bg-gray-100 text-gray-500 border-b-transparent hover:bg-gray-200"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
