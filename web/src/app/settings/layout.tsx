import type { Metadata } from "next";
const title = "Settings — rowlab";
const description =
  "Manage rowlab providers, organization storage, model usage, members and API keys.";
export const metadata: Metadata = {
  title: "Settings",
  description,
  alternates: { canonical: "/settings/" },
  openGraph: {
    type: "website",
    siteName: "rowlab",
    locale: "en_US",
    title,
    description,
    url: "/settings/",
    images: [
      {
        url: "/brand/social/settings.png",
        width: 1200,
        height: 630,
        type: "image/png",
        alt: "rowlab — Your workspace. Your controls.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    images: [{ url: "/brand/social/settings.png", alt: "rowlab — Your workspace. Your controls." }],
  },
};
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
