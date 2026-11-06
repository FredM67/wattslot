// Éléments d'affichage du serveur MCP de la sous-page « Assistant vocal » des Réglages : adresse
// en ligne de réglage, bouton « Copier ».

import { useState } from "react";

import { ApiError, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { mcpAddress, type Connection } from "./mcp";

/** Adresse interne du serveur MCP, à copier ou à corriger (et à oublier pour revenir à celle
 * trouvée par l'application), en ligne de réglage : `label` à gauche, l'adresse dessous, les
 * boutons à droite. */
export function McpAddress({
  connection,
  onChange,
  label,
}: {
  connection: Connection | null;
  onChange: (connection: Connection) => void;
  label: string;
}) {
  const { t } = useI18n();
  const address = mcpAddress(connection);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<"invalid" | "failed" | null>(null);

  const save = async (url: string | null) => {
    setError(null);
    try {
      onChange(await putJson<Connection>("api/assistant/connection", { mcp_url: url }));
      setEditing(null);
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 422 ? "invalid" : "failed");
    }
  };

  if (editing !== null) {
    return (
      <form
        className="assistant-address-form ui-setting-row"
        onSubmit={(event) => {
          event.preventDefault();
          void save(editing.trim());
        }}
      >
        <label>
          {t("assistant.address.label")}{" "}
          <input inputMode="url" value={editing} onChange={(event) => setEditing(event.target.value)} />
        </label>{" "}
        <button type="submit">{t("assistant.address.save")}</button>{" "}
        {connection?.saved && (
          <button type="button" onClick={() => void save(null)}>
            {t("assistant.address.reset")}
          </button>
        )}{" "}
        <button type="button" onClick={() => setEditing(null)}>
          {t("assistant.address.cancel")}
        </button>
        {error && <p role="alert">{t(`assistant.address.${error}`)}</p>}
      </form>
    );
  }
  const edit = (
    <button type="button" onClick={() => setEditing(address ?? "http://")}>
      {t("assistant.address.edit")}
    </button>
  );
  return (
    <div className="ui-setting-row">
      <span>
        <span className="ui-row-label">{label}</span>
        {address ? (
          <code className="ui-row-help assistant-address">{address}</code>
        ) : (
          <span className="ui-row-help">{t("assistant.address.unknown")}</span>
        )}
      </span>
      <span className="settings-actions">
        {address && <CopyButton text={address} label={t("assistant.copy_address")} />}
        {edit}
      </span>
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
    >
      {t(copied ? "assistant.copied" : "assistant.copy")}
    </button>
  );
}
