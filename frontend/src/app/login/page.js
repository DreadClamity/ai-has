"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearSession, setToken } from "../../lib/api";
import { homeFor } from "../../lib/auth";

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
    <div className="login-wrap">
      <form className="card login-box" onSubmit={submit}>
        <h2>AI-HAS IT Helpdesk</h2>
        <p className="muted">Sign in to continue</p>
        <label>Email</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        <label>Password</label>
        <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy} type="submit">
          {busy ? "Signing in..." : "Sign in"}
        </button>
        <div className="demo">
          <span className="muted">Demo accounts (capstone only):</span>
          <div className="demo-buttons">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.label}
                type="button"
                className="btn"
                onClick={() => {
                  setEmail(a.email);
                  setPassword(a.password);
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}