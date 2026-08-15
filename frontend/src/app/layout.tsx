import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TravelBuddy",
  description: "Trip planning with a deterministic scheduler and a verified budget.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
