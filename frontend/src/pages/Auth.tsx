import { useState } from "react";
import { post } from "../api/client";
import type { User } from "../components/AccountMenu";
import { BrandMark } from "../components/BrandMark";

export function Auth({
  onAuthenticated,
  message = "",
}: {
  onAuthenticated: (user: User) => void;
  message?: string;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">
            <BrandMark size={40} />
          </span>
          <h1>叙光集</h1>
        </div>
        <h2>{mode === "login" ? "登录创作空间" : "创建账号"}</h2>
        <form
          key={mode}
          onSubmit={async (event) => {
            event.preventDefault();
            const values = new FormData(event.currentTarget);
            if (
              mode === "register" &&
              values.get("password") !== values.get("confirm_password")
            ) {
              setError("两次输入的密码不一致。");
              return;
            }
            setBusy(true);
            setError("");
            try {
              onAuthenticated(
                await post<User>(`/auth/${mode}`, {
                  username: String(values.get("username") || "").trim(),
                  password: values.get("password"),
                }),
              );
            } catch (e) {
              setError(e instanceof Error ? e.message : "暂时无法登录");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            用户名
            <input
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={3}
              maxLength={32}
              pattern="[A-Za-z0-9_\-]{3,32}"
              placeholder="3–32 位字母、数字、下划线或短横线"
              disabled={busy}
              autoFocus
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
              minLength={8}
              maxLength={128}
              placeholder="至少 8 位"
              disabled={busy}
            />
          </label>
          {mode === "register" && (
            <label>
              确认密码
              <input
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                maxLength={128}
                disabled={busy}
              />
            </label>
          )}
          {(error || message) && (
            <p className="form-error" role="alert">
              {error || message}
            </p>
          )}
          <button type="submit" className="primary full-width" disabled={busy}>
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </button>
        </form>
        <button
          className="text-button auth-switch"
          disabled={busy}
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError("");
          }}
        >
          {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
        </button>
      </section>
    </main>
  );
}
