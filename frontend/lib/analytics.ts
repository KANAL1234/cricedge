import posthog from "posthog-js";

export const initAnalytics = () => {
  if (typeof window === "undefined") return;
  if (!process.env.NEXT_PUBLIC_POSTHOG_KEY) return;

  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    api_host: "https://app.posthog.com",
    capture_pageview: false, // we handle this manually
    persistence: "localStorage",
  });
};

export const trackEvent = (
  event: string,
  properties?: Record<string, unknown>
) => {
  if (typeof window === "undefined") return;
  try {
    posthog.capture(event, properties);
  } catch {
    // analytics never breaks the app
  }
};

export const identifyUser = (
  userId: string,
  properties: {
    email: string;
    subscription_tier: "free" | "pro" | "elite";
    created_at: string;
  }
) => {
  if (typeof window === "undefined") return;
  try {
    posthog.identify(userId, properties);
  } catch {
    // analytics never breaks the app
  }
};
