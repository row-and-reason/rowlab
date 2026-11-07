import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";

import { MeProvider } from "@/components/me";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const appUrl = new URL(process.env.NEXT_PUBLIC_APP_URL ?? "https://app.rowlab.dev");
const description =
  "Label, extract and rewrite tabular data with AI. Compare model outputs and inspect answers in the rowlab workspace.";

export const metadata: Metadata = {
  metadataBase: appUrl,
  title: { default: "rowlab — Data labeling workspace", template: "%s — rowlab" },
  description,
  applicationName: "rowlab",
  alternates: { canonical: "/" },
  robots: { index: false, follow: false },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "16x16 32x32 48x48" },
      { url: "/favicon.svg", type: "image/svg+xml", sizes: "any" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  openGraph: {
    type: "website",
    siteName: "rowlab",
    locale: "en_US",
    title: "rowlab — Data labeling workspace",
    description,
    url: "/",
    images: [
      {
        url: "/brand/social/app.png",
        width: 1200,
        height: 630,
        alt: "rowlab — From rows to answers.",
        type: "image/png",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "rowlab — Data labeling workspace",
    description,
    images: [{ url: "/brand/social/app.png", alt: "rowlab — From rows to answers." }],
  },
};
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#121116" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // next-themes sets the theme class before React hydrates.
      suppressHydrationWarning
    >
      <body className="flex h-full flex-col overflow-hidden">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <TooltipProvider>
            <MeProvider>{children}</MeProvider>
            <Toaster />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
