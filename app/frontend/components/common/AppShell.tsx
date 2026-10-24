"use client";
import Link from "next/link";
import { Menu, MessageSquare, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const links = [
  { href: "/", label: "Pemantauan" },
  { href: "/intelligence", label: "Perbandingan" },
  { href: "/model", label: "Data & metode" },
];
function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Beranda PasarPulse">
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
          stroke="#fff"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>PasarPulse</span>
    </Link>
  );
}
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const assistantAvailable =
    health.data?.reasoning_service.status === "healthy";
  useEffect(() => {
    setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) {
      dialog.current?.close();
      return;
    }
    dialog.current?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);
  const navigation = (mobile = false) => (
    <nav
      className={mobile ? "mobile-nav" : "primary-nav"}
      aria-label={mobile ? "Navigasi mobile" : "Navigasi utama"}
    >
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={pathname === link.href ? "page" : undefined}
          onClick={() => setOpen(false)}
        >
          {link.label}
        </Link>
      ))}
      {mobile && assistantAvailable && (
        <Link href="/assistant" onClick={() => setOpen(false)}>
          Asisten
        </Link>
      )}
    </nav>
  );
  return (
    <>
      <a href="#main-content" className="skip-link">
        Langsung ke konten
      </a>
      <header className="app-header">
        <div className="header-left">
          <Brand />
          {navigation()}
        </div>
        <div className="header-actions">
          {metadata.data && <StatusBadge label={metadata.data.mode_label} />}{" "}
          {assistantAvailable && (
            <Link href="/assistant" className="assistant-link">
              <MessageSquare size={15} />
              Asisten
            </Link>
          )}
          <button
            className="ui-button icon-only mobile-menu-button"
            aria-label="Buka navigasi"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <Menu size={18} />
          </button>
        </div>
      </header>
      <dialog
        ref={dialog}
        className="navigation-dialog"
        onCancel={() => setOpen(false)}
        aria-label="Navigasi"
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <Brand />
          <button
            className="ui-button icon-only"
            aria-label="Tutup navigasi"
            onClick={() => setOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        {navigation(true)}
      </dialog>
      <main
        id="main-content"
        className={pathname === "/" ? "app-main app-main--monitor" : "app-main"}
      >
        {children}
      </main>
    </>
  );
}
