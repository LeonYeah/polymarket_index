import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Polymarket Wallet Tracker",
  description: "Read-only dashboard for wallet research, SmartScore, markets, and alerts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link className="brand" href="/">
            Polymarket Wallet Tracker
          </Link>
          <nav className="nav">
            <Link href="/">Dashboard</Link>
            <a href={process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/docs"}>
              API
            </a>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
