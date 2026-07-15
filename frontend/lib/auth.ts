export type Session = {
  access_token: string;
  user_id: string;
  organization_id: string;
  organization_role?: string;
};

export const SESSION_KEY = "trade-axis-session";

export function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(SESSION_KEY);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (
      typeof parsed.access_token !== "string" ||
      typeof parsed.user_id !== "string" ||
      typeof parsed.organization_id !== "string"
    ) {
      return null;
    }
    return parsed as Session;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  window.localStorage.removeItem(SESSION_KEY);
}

export function authHeaders(session: Pick<Session, "access_token">): Record<string, string> {
  return { Authorization: `Bearer ${session.access_token}` };
}
