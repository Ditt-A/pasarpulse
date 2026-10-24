"use client";

import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Bell,
  ChartNoAxesCombined,
  ChevronRight,
  LayoutDashboard,
  Menu,
  MessageCircle,
  ShieldCheck,
  Sprout,
  X,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const links = [
  { href: "/", label: "Market overview", icon: LayoutDashboard },
  { href: "/alerts", label: "Alert queue", icon: Bell },
  { href: "/intelligence", label: "Regional intelligence", icon: Activity },
  { href: "/model", label: "Model performance", icon: ChartNoAxesCombined },
];
function Brand() {
  return (
    <Link href="/" className="brand" aria-label="PasarPulse home">
      <svg
        className="brand-mark"
        viewBox="0 0 38 40"
        fill="none"
        aria-hidden="true"
      >
        <path d="M7 24C4 11 15 4 31 5C32 19 25 29 14 27" fill="currentColor" />
        <path
          d="M8 34C10 25 16 18 25 12"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d="M8 23H15L18 16L21 23H28"
          stroke="#f2f6ec"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>
        <strong>PasarPulse</strong>
        <small>Food price intelligence</small>
      </span>
    </Link>
  );
}
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!menuOpen) {
      dialog.current?.close();
      return;
    }
    dialog.current?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [menuOpen]);
  const title =
    links.find((link) => link.href === pathname)?.label || "Research assistant";
  const sidebar = (mobile = false) => (
    <aside className="app-sidebar">
      <div className="flex items-center justify-between">
        <Brand />
        {mobile && (
          <button
            className="ui-button icon-only"
            aria-label="Close navigation"
            onClick={() => setMenuOpen(false)}
          >
            <X size={17} />
          </button>
        )}
      </div>
      <div className="sidebar-label">Workspace</div>
      <nav
        className="app-nav"
        aria-label={mobile ? "Mobile navigation" : "Main navigation"}
      >
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            href={href}
            key={href}
            aria-current={pathname === href ? "page" : undefined}
            onClick={() => setMenuOpen(false)}
          >
            <Icon size={17} strokeWidth={1.65} />
            {label}
            {pathname === href && <i className="nav-current" />}
          </Link>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <ShieldCheck
          size={22}
          strokeWidth={1.4}
          className="sidebar-note-icon"
        />
        <strong className="block text-xs font-semibold text-[#425a40]">
          Built for informed decisions.
        </strong>
        <p className="mt-2">
          Forecasts support monitoring and verification by your team.
        </p>
        <Link href="/model">
          Explore the methodology <ArrowUpRight size={13} />
        </Link>
        <div className="mt-7 flex items-center gap-2 text-[10px]">
          <Sprout size={12} /> Indonesian food markets
        </div>
      </div>
    </aside>
  );
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {sidebar()}
      <dialog
        className="mobile-dialog"
        ref={dialog}
        onCancel={() => setMenuOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setMenuOpen(false);
        }}
        aria-label="Navigation"
      >
        {sidebar(true)}
      </dialog>
      <div className="app-body">
        <header className="app-header">
          <div className="breadcrumbs">
            <button
              className="ui-button icon-only mobile-menu-button"
              aria-label="Open navigation"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(true)}
            >
              <Menu size={17} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={12} />
            <strong className="hidden sm:inline">{title}</strong>
            <strong className="sm:hidden">PasarPulse</strong>
          </div>
          <div className="header-actions">
            {metadata.data && <StatusBadge label={metadata.data.mode_label} />}
            <button
              onClick={() => router.push("/assistant")}
              aria-label="Ask PasarPulse"
              className="ui-button primary"
            >
              <MessageCircle size={15} />
              <span className="assistant-label">Ask PasarPulse</span>
            </button>
          </div>
        </header>
        <main id="main-content" className="app-main page-enter" key={pathname}>
          {children}
        </main>
        <footer className="app-footer">
          <span>
            Decision support for food-price monitoring. Forecasts are estimates;
            historical outcomes remain separate from forecast-time information.
          </span>
          <span>PasarPulse · Indonesia</span>
        </footer>
      </div>
    </>
  );
}
