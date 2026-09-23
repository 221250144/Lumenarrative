import { useState } from "react";
import { post } from "../api/client";
import { Modal } from "./Modal";
import { Icon } from "./Icon";

export type User = { id: string; username: string };

export function AccountMenu({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  return (
    <>
      <button
        className="account-button"
        onClick={() => {
          setOpen(true);
          setError("");
          setSuccess(false);
        }}
        aria-label={`账号：${user.username}`}
      >
        <Icon name="user" size={16} />
        <span>{user.username}</span>
      </button>
      {open && (
        <Modal
          title="我的账号"
          titleId="account-title"
          busy={busy}
          onClose={() => setOpen(false)}
        >
          <p className="account-name">{user.username}</p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const values = new FormData(form);
              if (
                values.get("new_password") !== values.get("confirm_password")
              ) {
                setError("两次输入的新密码不一致。");
                return;
              }
              setBusy(true);
              setError("");
              setSuccess(false);
              try {
                await post("/auth/password", {
                  current_password: values.get("current_password"),
                  new_password: values.get("new_password"),
                });
                form.reset();
                setSuccess(true);
              } catch (e) {
                setError(e instanceof Error ? e.message : "修改失败");
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              当前密码
              <input
                name="current_password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
                disabled={busy}
              />
            </label>
            <label>
              新密码
              <input
                name="new_password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                maxLength={128}
                placeholder="至少 8 位"
                disabled={busy}
              />
            </label>
            <label>
              确认新密码
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
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            {success && (
              <p className="form-success" role="status">
                密码已修改
              </p>
            )}
            <button
              className="primary full-width"
              type="submit"
              disabled={busy}
            >
              {busy ? "正在保存…" : "修改密码"}
            </button>
          </form>
          <button
            className="small-button full-width account-logout"
            disabled={busy}
            onClick={onLogout}
          >
            退出登录
          </button>
        </Modal>
      )}
    </>
  );
}
