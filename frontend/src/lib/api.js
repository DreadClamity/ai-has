export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("aihas_token");
}

export function setToken(token) {
  localStorage.setItem("aihas_token", token);
}

export function clearSession() {
  if (typeof window !== "undefined") localStorage.removeItem("aihas_token");
}

function errorMessage(data, status) {
  if (data && data.detail) {
    return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  }
  return `Request failed (${status})`;
}

function handleUnauthorized() {
  clearSession();
  if (typeof window !== "undefined") window.location.href = "/login";
}

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
  if (res.status === 401 && path !== "/auth/login") {
    handleUnauthorized();
    throw new Error("Session expired. Please log in again.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data;
}

export async function streamChat(body, { onMeta, onToken, onDone, signal }) {
  const res = await fetch(`${API_URL}/chat/message/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("Session expired. Please log in again.");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(errorMessage(data, res.status));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();

    for (const block of blocks) {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      const parsed = JSON.parse(data);
      if (event === "meta" && onMeta) onMeta(parsed);
      else if (event === "token" && onToken) onToken(parsed.text);
      else if (event === "done") {
        onDone?.(parsed);
        return;
      }
    }
  }
  throw new Error("The reply was interrupted. Check your conversations before retrying.");
}
