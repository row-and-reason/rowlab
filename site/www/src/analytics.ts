// PostHog with its default capture (pageviews, clicks, web vitals). Only on the real site: a build
// served elsewhere, or without a token, sends nothing.
import posthog from "posthog-js";

const token = import.meta.env.PUBLIC_POSTHOG_TOKEN;
if (token && location.origin === new URL(import.meta.env.SITE).origin) {
  posthog.init(token, {
    api_host: import.meta.env.PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com",
    defaults: "2026-08-30",
  });
}
