import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/components/common/QueryProvider";
import { AppShell } from "@/components/common/AppShell";

export const metadata: Metadata = {
  title: "PasarPulse | Pemantauan harga pangan",
  description:
    "Pemantauan proyeksi harga pangan, perbandingan wilayah, dan sumber data PasarPulse.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
