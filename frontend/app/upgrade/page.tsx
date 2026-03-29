"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

const cn = (...args: any[]) => twMerge(clsx(args));

interface Plan {
  id: "free" | "pro" | "elite";
  name: string;
  price: string;
  priceNote: string;
  badge?: string;
  features: string[];
  color: string;
  borderColor: string;
  buttonColor: string;
}

const PLANS: Plan[] = [
  {
    id: "free",
    name: "FREE",
    price: "₹0",
    priceNote: "forever",
    features: [
      "Match schedules & scores",
      "Basic team information",
      "Venue overview",
      "5 match views per day",
    ],
    color: "text-muted",
    borderColor: "border-border",
    buttonColor: "border border-border text-muted hover:text-white",
  },
  {
    id: "pro",
    name: "PRO",
    price: "₹299",
    priceNote: "per month",
    badge: "MOST POPULAR",
    features: [
      "Everything in FREE",
      "Full ownership predictions",
      "Captain & VC recommendations",
      "All match access",
      "Form engine scores",
      "Differential alerts",
    ],
    color: "text-warning",
    borderColor: "border-warning/50",
    buttonColor: "bg-warning text-background hover:bg-warning/90",
  },
  {
    id: "elite",
    name: "ELITE",
    price: "₹799",
    priceNote: "per month",
    features: [
      "Everything in PRO",
      "WhatsApp alerts on XI drop",
      "Advanced differential scores",
      "Monte Carlo projections",
      "API access",
      "Priority support",
    ],
    color: "text-accent",
    borderColor: "border-accent/50",
    buttonColor: "bg-accent text-background hover:bg-accent/90",
  },
];

export default function UpgradePage() {
  const { subscriptionTier } = useAuthStore();
  const [loading, setLoading] = useState<string | null>(null);

  async function handleUpgrade(planId: string) {
    if (planId === "free" || planId === subscriptionTier) return;

    setLoading(planId);
    try {
      await api.post("/billing/subscribe", { plan: planId });
      toast.success("Upgrade successful!", {
        description: `You are now on the ${planId.toUpperCase()} plan`,
      });
    } catch {
      toast.info("Payment integration coming soon", {
        description: "We'll notify you when billing goes live",
      });
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="max-w-screen-lg mx-auto px-4 py-8 space-y-6">
      <div className="text-center space-y-1">
        <div className="font-mono text-accent text-lg font-bold tracking-widest">
          CHOOSE YOUR PLAN
        </div>
        <div className="font-mono text-muted text-xs">
          Upgrade for full ownership data and captain intelligence
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {PLANS.map((plan) => {
          const isCurrent = subscriptionTier === plan.id;
          return (
            <div
              key={plan.id}
              className={cn(
                "relative border rounded p-5 space-y-4 transition-colors bg-surface",
                isCurrent ? plan.borderColor : "border-border hover:" + plan.borderColor.replace("border-", "border-")
              )}
            >
              {plan.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="font-mono text-[10px] bg-warning text-background px-3 py-0.5 rounded font-bold">
                    {plan.badge}
                  </span>
                </div>
              )}

              <div className="space-y-1">
                <div className={cn("font-mono text-sm font-bold tracking-widest", plan.color)}>
                  {plan.name}
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="font-mono text-2xl font-bold text-white">
                    {plan.price}
                  </span>
                  <span className="font-mono text-muted text-xs">{plan.priceNote}</span>
                </div>
              </div>

              <div className="space-y-2">
                {plan.features.map((f) => (
                  <div key={f} className="flex items-start gap-2">
                    <Check size={12} className={cn("mt-0.5 shrink-0", plan.color)} />
                    <span className="font-mono text-xs text-muted">{f}</span>
                  </div>
                ))}
              </div>

              <button
                onClick={() => handleUpgrade(plan.id)}
                disabled={isCurrent || loading === plan.id || plan.id === "free"}
                className={cn(
                  "w-full font-mono text-xs font-bold py-3 rounded transition-colors min-h-[44px] disabled:opacity-50",
                  isCurrent
                    ? "border border-accent/30 text-accent cursor-default"
                    : plan.buttonColor
                )}
              >
                {isCurrent
                  ? "CURRENT PLAN"
                  : loading === plan.id
                  ? "PROCESSING..."
                  : plan.id === "free"
                  ? "DOWNGRADE"
                  : `UPGRADE TO ${plan.name}`}
              </button>
            </div>
          );
        })}
      </div>

      <div className="text-center font-mono text-[10px] text-muted">
        All plans include 7-day free trial · Cancel anytime · Prices in INR
      </div>
    </div>
  );
}
