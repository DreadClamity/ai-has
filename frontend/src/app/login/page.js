"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearSession, setToken } from "../../lib/api";
import { homeFor } from "../../lib/auth";
import { Brand } from "../../components/Header";
import ThemeToggle from "../../components/ThemeToggle";

const DEMO_ACCOUNTS = [
  { label: "Employee", email: "employee@aihas.local", password: "Employee123!" },
  { label: "Agent", email: "agent@aihas.local", password: "Agent123!" },
  { label: "Admin", email: "admin@aihas.local", password: "Admin123!" },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = await api("/auth/login", {
        method: "POST",
        form: { username: email, password },
      });
      setToken(token.access_token);
      const me = await api("/auth/me");
      router.replace(homeFor(me.role));
    } catch (err) {
      clearSession();
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="header">
        <div className="topbar"><Brand /><ThemeToggle /></div>
      </header>
      <main className="container login-wrap">
      <section className="login-intro">
        <h1>Get help with your IT issues</h1>
        <p className="muted">Find answers from your IT knowledge base or pick up the conversation with the service desk.</p>
      </section>
      <form className="card login-box" onSubmit={submit}>
        <h2>Sign in to your workspace</h2>
        <label htmlFor="email">Work email</label>
        <input id="email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="username" required />
        <label htmlFor="password">Password</label>
        <input id="password" value={password} onChange={(e) => setPassword(e.target.value)} type={showPassword ? "text" : "password"} autoComplete="current-password" required />
        <label className="checkbox"><input type="checkbox" checked={showPassword} onChange={(e) => setShowPassword(e.target.checked)} /> Show password</label>
        {error && <div className="error" role="alert">{error}</div>}
        <button className="btn btn-primary" disabled={busy} type="submit">
          {busy ? "Signing in..." : "Sign in"}
        </button>
        <div className="demo">
          <p className="muted">Choose a demo account to fill the sign-in form.</p>
          <div className="demo-buttons">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.label}
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => {
                  setEmail(a.email);
                  setPassword(a.password);
                  setShowPassword(false);
                  setError("");
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </form>
      </main>
    </>
  );
}
