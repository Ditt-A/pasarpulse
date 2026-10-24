"use client";

import Link from "next/link";
import { Activity, Bell, BrainCircuit, LayoutDashboard, MessageCircle, Radio } from "lucide-react";
import { usePathname } from "next/navigation";
import { useDashboardStore } from "@/stores/dashboard";

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/intelligence", label: "Intelligence", icon: Activity },
  { href: "/model", label: "Model", icon: BrainCircuit },
];
const proxyBasePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
const proxiedPath = (path: string) => `${proxyBasePath}${path}`;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const setCopilotOpen = useDashboardStore((state) => state.setCopilotOpen);

  if (pathname === "/" || pathname === "/assistant") {
    return <div className="h-dvh overflow-hidden bg-white text-slate-900">{children}</div>;
  }

  return (
    <div className="min-h-screen bg-ink grid-noise">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-ink/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-5 px-5 py-3 lg:px-8">
          <Link href={proxiedPath("/")} className="flex min-w-fit items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyanpulse/40 bg-cyanpulse/10 text-cyanpulse"><Radio size={18} /></div>
            <div>
              <div className="text-sm font-semibold tracking-[.18em] text-white">PASARPULSE</div>
              <div className="hidden text-[10px] uppercase tracking-[.16em] text-slate-400 md:block">National Food Price Early-Warning Intelligence</div>
            </div>
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {links.map(({ href, label, icon: Icon }) => <Link key={href} href={proxiedPath(href)} className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-slate-400 transition hover:bg-white/5 hover:text-white"><Icon size={14} />{label}</Link>)}
          </nav>
          <button onClick={() => setCopilotOpen(true)} className="flex items-center gap-2 rounded-lg border border-cyanpulse/40 bg-cyanpulse/10 px-3 py-2 text-xs font-semibold text-cyanpulse transition hover:bg-cyanpulse/20"><MessageCircle size={15} /> <span className="hidden sm:inline">Ask PasarPulse</span></button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1680px] px-5 py-5 pb-20 lg:px-8">{children}</main>
      <footer className="border-t border-line/60 px-5 py-5 text-center text-[11px] text-slate-500">PasarPulse is a decision-support prototype. Historical replay keeps later realized prices separate from forecast-time information.</footer>
    </div>
  );
}
