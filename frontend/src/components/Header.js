"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "../lib/api";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { href: "/chat", label: "Get help", roles: ["employee", "agent", "admin"] },
  { href: "/agent", label: "Ticket queue", roles: ["agent", "admin"] },
  { href: "/admin", label: "Admin dashboard", roles: ["admin"] },
];

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">H</span>
      <strong>AI-HAS</strong>
      <span className="brand-caption">IT Helpdesk</span>
    </div>
  );
}

export default function Header({ user }) {
  const router = useRouter();
  const pathname = usePathname();

  const logout = () => {
    clearSession();
    router.replace("/login");
  };

  return (
    <header className="header">
      <div className="topbar">
        <Brand />
        <div className="who">
          <span className="identity"><strong>{user.full_name}</strong><span className="badge">{user.role}</span></span>
          <ThemeToggle />
          <button className="btn" onClick={logout}>Sign out</button>
        </div>
      </div>
      <nav className="workspace-nav" aria-label="Workspace">
        {LINKS.filter((link) => link.roles.includes(user.role)).map((link) => (
          <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined}>
            {link.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
