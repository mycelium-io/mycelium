import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "mycelium",
  description: "Multi-agent coordination + persistent memory",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-bg text-[#e2eaf6] antialiased">
        {children}
      </body>
    </html>
  );
}
