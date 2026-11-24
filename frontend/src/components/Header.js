"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearSession } from "../lib/api";

const LINKS = [
  { href: "/chat", label: "Chat", roles: ["employee", "agent", "admin"] },
  { href: "/agent", label: "Agent Queue", roles: ["agent", "admin"] },
  { href: "/admin", label: "Admin Dashboard", roles: ["admin"] },
];

export default function Header({ user }) {
  const router = useRouter();

  const logout = () => {
    clearSession();
    router.replace("/login");
  };

  return (
    <header className="header">
      <div className="brand">
        AI-HAS <span>IT Helpdesk</span>
      </div>
      <nav>
        {LINKS.filter((l) => l.roles.includes(user.role)).map((l) => (
          <Link key={l.href} href={l.href}>
            {l.label}
          </Link>
        ))}
      </nav>
      <div className="who">
        {user.full_name} <span className="badge">{user.role}</span>
        <button className="btn" onClick={logout}>
          Log out
        </button>
      </div>
    </header>
  );
}