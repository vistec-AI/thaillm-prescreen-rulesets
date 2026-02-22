import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "@/lib/context/AppContext";

export const metadata: Metadata = {
  title: "Prescreen Initial Assessment Rules Inspector",
  description: "Visualize and edit prescreening rule graphs",
  icons: { icon: "/brand/thaillm.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
