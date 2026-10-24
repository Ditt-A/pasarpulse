import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/components/common/QueryProvider";
import { AppShell } from "@/components/common/AppShell";

export const metadata: Metadata = {
  title: "PasarPulse | National Food Price Early-Warning Intelligence",
  description: "Operational replay and evidence interface for PasarPulse research artifacts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <QueryProvider><AppShell>{children}</AppShell></QueryProvider>
      </body>
    </html>
  );
}
