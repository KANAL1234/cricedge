"use client";

import Link from "next/link";

export default function SignupPage() {
  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm text-center space-y-6">
        <div className="space-y-1">
          <div className="flex items-center justify-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span className="font-mono text-accent text-xl font-bold tracking-[0.3em]">
              CRICEDGE
            </span>
          </div>
          <div className="font-mono text-muted text-xs tracking-widest">
            CREATE ACCOUNT
          </div>
        </div>

        <div className="border border-border rounded p-6 space-y-3 bg-surface">
          <div className="font-mono text-accent text-sm font-bold">
            REGISTRATION COMING SOON
          </div>
          <div className="font-mono text-muted text-xs leading-relaxed">
            User accounts and subscriptions are under development.
            All features are currently open access.
          </div>
          <Link
            href="/"
            className="block font-mono text-xs text-accent border border-accent/30 rounded px-4 py-3 hover:bg-accent/5 transition-colors min-h-[44px] flex items-center justify-center"
          >
            GO TO DASHBOARD
          </Link>
        </div>
      </div>
    </div>
  );
}
