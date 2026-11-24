"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "./api";

export function homeFor(role) {
  if (role === "admin") return "/admin";
  if (role === "agent") return "/agent";
  return "/chat";
}

export function useRequireRole(allowedRoles) {
  const router = useRouter();
  const [user, setUser] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api("/auth/me")
      .then((me) => {
        if (allowedRoles.includes(me.role)) setUser(me);
        else router.replace(homeFor(me.role));
      })
      .catch(() => router.replace("/login"));
  }, []);

  return user;
}