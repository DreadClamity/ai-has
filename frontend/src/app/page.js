"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "../lib/api";
import { homeFor } from "../lib/auth";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api("/auth/me")
      .then((me) => router.replace(homeFor(me.role)))
      .catch(() => router.replace("/login"));
  }, []);

  return <p style={{ padding: 24 }}>Loading...</p>;
}