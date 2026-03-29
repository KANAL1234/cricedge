"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { useUIStore, useAuthStore } from "@/lib/store";
import getSocket from "@/lib/socket";

const NAV_LINKS = [
  { label: "MATCHES", href: "/matches" },
  { label: "PLAYERS", href: "/players" },
  { label: "VENUES", href: "/venues" },
  { label: "MY TEAMS", href: "/teams" },
];

const TIER_STYLES: Record<string, string> = {
  free: "text-muted border-muted",
  pro: "text-warning border-warning",
  elite: "text-accent border-accent",
};

export default function Navbar() {
  const pathname = usePathname();
  const { toggleSidebar } = useUIStore();
  const { user, subscriptionTier } = useAuthStore();
  const [socketDisconnected, setSocketDisconnected] = useState(false);

  useEffect(() => {
    const s = getSocket();
    const handleDisconnect = () => setSocketDisconnected(true);
    const handleConnect = () => setSocketDisconnected(false);

    s.on("disconnect", handleDisconnect);
    s.on("connect", handleConnect);

    return () => {
      s.off("disconnect", handleDisconnect);
      s.off("connect", handleConnect);
    };
  }, []);

  const initials = user?.email
    ? user.email.slice(0, 2).toUpperCase()
    : "GU";

  const tierStyle = TIER_STYLES[subscriptionTier] ?? TIER_STYLES.free;

  return (
    <header className="sticky top-0 z-40 h-12 bg-background border-b border-border flex items-center px-4 justify-between">
      {/* Left: logo */}
      <div className="flex items-center gap-3">
        <button
          className="md:hidden min-h-[44px] min-w-[44px] flex items-center justify-center text-muted hover:text-white"
          onClick={toggleSidebar}
          aria-label="Toggle sidebar"
        >
          <Menu size={18} />
        </button>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <span className="font-mono text-accent font-bold tracking-[0.3em] text-sm">
            CRICEDGE
          </span>
        </div>
      </div>

      {/* Center: nav links (desktop only) */}
      <nav className="hidden md:flex items-center gap-6">
        {NAV_LINKS.map((link) => {
          const isActive = pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`font-mono text-xs transition-colors ${
                isActive
                  ? "text-accent"
                  : "text-muted hover:text-white"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>

      {/* Right: status + avatar */}
      <div className="flex items-center gap-3">
        {socketDisconnected && (
          <span className="font-mono text-[10px] text-warning animate-pulse border border-warning px-2 py-0.5 rounded">
            RECONNECTING...
          </span>
        )}

        <span
          className={`font-mono text-[10px] border px-2 py-0.5 rounded ${tierStyle}`}
        >
          {subscriptionTier.toUpperCase()}
        </span>

        <div
          className="w-6 h-6 rounded-full bg-surface-2 border border-border flex items-center justify-center font-mono text-[9px] text-muted select-none"
          title={user?.email ?? "Guest"}
        >
          {initials}
        </div>
      </div>
    </header>
  );
}
