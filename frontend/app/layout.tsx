import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "AgentFlow",
  description: "Open-source multi-agent runtime",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="min-h-screen flex flex-col">
            <header className="border-b border-border px-6 py-4 flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2">
                <span className="text-accent font-mono text-lg">▲</span>
                <span className="font-semibold tracking-tight">AgentFlow</span>
                <span className="text-xs text-muted ml-2">runtime console</span>
              </Link>
              <nav className="flex gap-4 text-sm text-muted">
                <Link href="/runs" className="hover:text-text">
                  Runs
                </Link>
                <a
                  href="http://localhost:8000/docs"
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-text"
                >
                  API
                </a>
              </nav>
            </header>
            <main className="flex-1 px-6 py-6">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
