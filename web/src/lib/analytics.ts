import posthog from "posthog-js";

import type { Me } from "@/lib/api/client";

// PostHog with its default capture, identified as the signed-in person and their organisation.
// The server sends a token only when it collects analytics (hosted, with ROWLAB_POSTHOG_TOKEN), so
// locally and on servers without one, nothing runs. What is captured is set in PostHog, not here.

let started = false;

export function startAnalytics(me: Me) {
  if (started || !me.analytics || !me.user) return;
  try {
    posthog.init(me.analytics.token, { api_host: me.analytics.host, defaults: "2026-08-30" });
    started = true;
    posthog.identify(me.user.id, { email: me.user.email, name: me.user.name });
    posthog.group("organization", me.org.id, { name: me.org.name });
    posthog.register({ organization_id: me.org.id, organization_role: me.role });
  } catch {
    // Analytics must not break the app.
  }
}

/** Before signing out, so the next person on this browser starts as someone else. */
export function resetAnalytics() {
  if (!started) return;
  try {
    posthog.reset();
  } catch {
    // Nor stop signing out.
  }
}
