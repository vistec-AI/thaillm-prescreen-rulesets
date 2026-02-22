"use client";

import { useApp, useVersionPolling } from "@/lib/context/AppContext";
import Titlebar from "@/components/layout/Titlebar";
import TabBar from "@/components/layout/TabBar";
import Footer from "@/components/layout/Footer";
import LoadingOverlay from "@/components/layout/LoadingOverlay";
import ValidationSection from "@/components/shared/ValidationSection";
import DemographicTab from "@/components/demographic/DemographicTab";
import ErTab from "@/components/er/ErTab";
import GraphTab from "@/components/graph/GraphTab";

export default function Home() {
  const { activeTab } = useApp();

  // Start version polling on the root page
  useVersionPolling();

  return (
    <div className="flex flex-col h-screen p-2 md:px-3">
      <LoadingOverlay />
      <Titlebar />
      <TabBar />
      <ValidationSection />

      {/* Tab panels — only the active one renders to avoid unnecessary Cytoscape re-inits */}
      <div className="flex-1 flex flex-col min-h-0">
        {activeTab === "demographic" && <DemographicTab />}
        {activeTab === "er" && <ErTab />}
        {activeTab === "graph" && <GraphTab />}
      </div>

      <Footer />
    </div>
  );
}
