import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Daybreak — Good news, well reported.",
  description:
    "An autonomous, constructive newsroom. Daybreak surfaces good, verified news — progress, recovery and solutions that actually work — and publishes full articles you can read here.",
  openGraph: {
    title: "Daybreak — Good news, well reported.",
    description:
      "An autonomous, constructive newsroom. Progress and solutions, never sacrificing the truth.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
