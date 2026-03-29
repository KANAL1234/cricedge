import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

const cn = (...args: any[]) => twMerge(clsx(args));

export function SkeletonCard() {
  return (
    <div className="border border-border rounded p-4 space-y-3 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-4 w-32 bg-surface-2 rounded" />
        <div className="h-4 w-14 bg-surface-2 rounded" />
      </div>
      <div className="h-3 w-48 bg-surface-2 rounded" />
      <div className="flex gap-2">
        <div className="h-5 w-12 bg-surface-2 rounded" />
        <div className="h-5 w-20 bg-surface-2 rounded" />
      </div>
    </div>
  );
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 py-2 animate-pulse">
      <div className="h-4 w-28 bg-surface-2 rounded" />
      <div className="h-4 w-10 bg-surface-2 rounded" />
      <div className="h-4 w-16 bg-surface-2 rounded" />
      <div className="h-4 w-20 bg-surface-2 rounded" />
    </div>
  );
}

export function SkeletonText({ className }: { className?: string }) {
  return (
    <div className={cn("h-3 bg-surface-2 rounded animate-pulse", className)} />
  );
}
