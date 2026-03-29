import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import AnalyticsProvider from "@/components/AnalyticsProvider";

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "CricEdge Terminal",
  description: "Fantasy cricket intelligence platform for Dream11 & My11Circle",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#080C10",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${ibmPlexMono.variable} ${ibmPlexSans.variable} bg-background text-white font-sans antialiased`}
      >
        <AnalyticsProvider>
          <div className="min-h-screen flex flex-col">
            <Navbar />
            <div className="flex flex-1">
              <Sidebar />
              <main className="flex-1 min-w-0">{children}</main>
            </div>
          </div>
        </AnalyticsProvider>
        <Toaster
          theme="dark"
          toastOptions={{
            style: {
              background: "#0D1117",
              border: "1px solid #21262D",
              color: "#fff",
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "12px",
            },
          }}
        />
      </body>
    </html>
  );
}
