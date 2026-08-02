"use client";

import { FormEvent, useState } from "react";
import { authHeaders, saveSession, type Session } from "../../lib/auth";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Membership = { organization_id: string; role: string };

async function requestJson<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data: unknown = await response.json();
  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string"
        ? data.detail
        : "认证失败";
    throw new Error(detail);
  }
  return data as T;
}

export default function LoginPage() {
  const [registering, setRegistering] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = registering
      ? {
          organization_name: String(form.get("organization") ?? ""),
          display_name: String(form.get("name") ?? ""),
          email: String(form.get("email") ?? ""),
          password: String(form.get("password") ?? ""),
        }
      : { email: String(form.get("email") ?? ""), password: String(form.get("password") ?? "") };
    setPending(true); setMessage("");
    try {
      const authSession = await requestJson<Session>(`${apiUrl}/platform/auth/${registering ? "register" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const membership = await requestJson<Membership>(
        `${apiUrl}/platform/organizations/${authSession.organization_id}/membership`,
        { headers: authHeaders(authSession) }
      );
      saveSession({ ...authSession, organization_role: membership.role });
      window.location.assign("/");
    } catch (error) { setMessage(error instanceof Error ? error.message : "认证失败"); }
    finally { setPending(false); }
  }

  return <main style={{ maxWidth: 440, margin: "64px auto", padding: 24, fontFamily: "Arial, sans-serif" }}>
    <p style={{ color: "#0b7285", fontWeight: 700 }}>TRADE AXIS</p>
    <h1>{registering ? "创建工作区" : "登录"}</h1>
    <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
      {registering && <><label>组织名称<input name="organization" required style={{ width: "100%" }} /></label><label>姓名<input name="name" required style={{ width: "100%" }} /></label></>}
      <label>邮箱<input name="email" type="email" required style={{ width: "100%" }} /></label>
      <label>密码<input name="password" type="password" minLength={12} required style={{ width: "100%" }} /></label>
      {message && <p role="alert" style={{ color: "#c92a2a" }}>{message}</p>}
      <button type="submit" disabled={pending}>{pending ? "请稍候..." : registering ? "创建账号" : "登录"}</button>
    </form>
    <button type="button" onClick={() => { setRegistering(!registering); setMessage(""); }} style={{ marginTop: 18 }}>
      {registering ? "已有账号？去登录" : "第一次使用？创建工作区"}
    </button>
  </main>;
}
