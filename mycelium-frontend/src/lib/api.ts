const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8888";

export async function fetchRooms() {
  const res = await fetch(`${API}/rooms`, { cache: "no-store" });
  return res.json();
}

export async function fetchRoom(name: string) {
  const res = await fetch(`${API}/rooms/${name}`, { cache: "no-store" });
  return res.json();
}

export async function createRoom(data: { name: string; trigger_config?: object; is_persistent?: boolean }) {
  const res = await fetch(`${API}/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, is_public: true }),
  });
  return res.json();
}

export async function fetchMemories(roomName: string, prefix?: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (prefix) params.set("prefix", prefix);
  const res = await fetch(`${API}/rooms/${roomName}/memory?${params}`, { cache: "no-store" });
  return res.json();
}

export async function searchMemories(roomName: string, query: string) {
  const res = await fetch(`${API}/rooms/${roomName}/memory/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 10 }),
  });
  return res.json();
}

export async function fetchCatchup(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/catchup`, { cache: "no-store" });
  return res.json();
}

export async function fetchMessages(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/messages`, { cache: "no-store" });
  return res.json();
}

export async function fetchSessions(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/sessions`, { cache: "no-store" });
  if (!res.ok) return { sessions: [], total: 0 };
  return res.json();
}

export async function fetchChildRooms(parentName: string) {
  const res = await fetch(`${API}/rooms?name=${encodeURIComponent(parentName + ":session:")}`, { cache: "no-store" });
  if (!res.ok) return [];
  const rooms = await res.json();
  return rooms.filter((r: any) => r.parent_namespace === parentName);
}

export function getSSEUrl(roomName: string) {
  return `${API}/rooms/${roomName}/messages/stream`;
}
