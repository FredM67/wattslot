// Sous-page « Assistant vocal » des Réglages : l'état du serveur MCP en carte (comme la page
// Assistant), puis des listes de réglages comme les autres pages : le serveur MCP (adresse,
// intégration dans Home Assistant), l'assistant préféré de HA avec son agent de conversation
// (/api/assistant/home), Open WebUI en appel direct (`OpenWebUISettings`) et, pour aller plus
// loin, le branchement de l'Assist pas à pas (avec le prompt conseillé) et les outils dans
// Open WebUI. L'application ne garde aucun réglage de l'assistant de HA : « Enregistrer » le
// modifie dans HA.

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { checkTitle, mcpAddress, useConnection, useMcpCheck } from "../assistant/mcp";
import { CopyButton, McpAddress } from "../assistant/McpParts";
import { useI18n } from "../i18n/I18nProvider";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";
import StateMessage from "../ui/StateMessage";
import OpenWebUISettings, { OpenWebUITools } from "./OpenWebUISettings";

interface Named {
  id: string;
  name: string;
}

interface AssistantHome {
  connected: boolean;
  mcp: { title: string; state: string }[];
  pipelines: (Named & { conversation_engine: string | null })[];
  preferred_pipeline: string | null;
  agents: Named[];
}

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; home: AssistantHome };
type Save = "idle" | "saving" | "saved" | "invalid" | "failed";

// États d'une entrée de configuration de HA, regroupés pour l'affichage.
function mcpState(state: string): "loaded" | "error" | "not_loaded" {
  if (state === "loaded") return "loaded";
  if (state === "not_loaded") return "not_loaded";
  return "error";
}

export default function VoiceSettings() {
  const { t } = useI18n();
  const [connection, setConnection] = useConnection();
  const [check, verify] = useMcpCheck();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // « Réessayer »
  const [pipeline, setPipeline] = useState<string>("");
  const [agent, setAgent] = useState<string>("");
  const [save, setSave] = useState<Save>("idle");

  const show = (home: AssistantHome) => {
    const preferred = home.pipelines.find((p) => p.id === home.preferred_pipeline) ?? home.pipelines[0];
    setLoad({ status: "ready", home });
    setPipeline(preferred?.id ?? "");
    setAgent(preferred?.conversation_engine ?? "");
  };

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantHome>("api/assistant/home", controller.signal)
      .then(show)
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  const onSave = async () => {
    setSave("saving");
    try {
      show(await putJson<AssistantHome>("api/assistant/home", { pipeline_id: pipeline, conversation_engine: agent }));
      setSave("saved");
    } catch (error) {
      setSave(error instanceof ApiError && error.status === 422 ? "invalid" : "failed");
    }
  };

  // Pastille de la carte d'état : mêmes couleurs que l'état de l'application.
  const level = check.status === "ok" ? "ok" : check.status === "failed" ? "blocking" : "setup";

  return (
    <section className="voice-settings settings-page" aria-labelledby="voice-title">
      <h2 id="voice-title" className="visually-hidden">
        {t("nav.voice")}
      </h2>

      <p className="settings-note settings-intro">{t("assistant.intro")}</p>
      <div className="ui-card settings-state">
        <span className="status-dot" data-level={level} aria-hidden="true" />
        <span className="settings-state-text">
          <span className="ui-row-label">{t(checkTitle(check))}</span>
          {check.status === "ok" && (
            <span role="status" className="ui-row-help">
              {t("assistant.check.ok", { tools: check.tools })}
            </span>
          )}
          {check.status === "failed" && (
            <span role="alert" className="ui-row-help">
              {t("assistant.check.failed", { detail: check.detail })}
            </span>
          )}
        </span>
        <button
          type="button"
          className="ui-button ui-button-quiet"
          disabled={check.status === "checking"}
          onClick={() => void verify()}
        >
          {t(check.status === "checking" ? "assistant.check.checking" : "assistant.check.run")}
        </button>
      </div>

      <h3 className="home-summary-heading">{t("settings.voice.server")}</h3>
      <SettingList>
        <McpAddress connection={connection} onChange={setConnection} label={t("settings.voice.address")} />
        {load.status === "ready" && load.home.connected && <McpRows home={load.home} />}
      </SettingList>
      <p className="settings-note">
        {t(connection?.mode === "addon" ? "assistant.step1.addon" : "assistant.step1.standalone")}
      </p>

      {load.status === "loading" && <StateMessage kind="loading" title={t("settings.loading")} />}
      {load.status === "error" && (
        <StateMessage
          kind="error"
          title={t("settings.error")}
          onRetry={() => {
            setLoad({ status: "loading" });
            setAttempt((count) => count + 1);
          }}
        />
      )}
      {load.status === "ready" && (
        <HomeAssistantPart
          home={load.home}
          pipeline={pipeline}
          agent={agent}
          save={save}
          onPipeline={(id) => {
            setSave("idle");
            setPipeline(id);
            setAgent(load.home.pipelines.find((p) => p.id === id)?.conversation_engine ?? "");
          }}
          onAgent={(id) => {
            setSave("idle");
            setAgent(id);
          }}
          onSave={() => void onSave()}
        />
      )}

      <OpenWebUISettings />

      <h3 className="home-summary-heading">{t("nav.more")}</h3>
      <SettingList>
        <SetupSteps mcpUrl={mcpAddress(connection)} open={check.status === "failed"} />
        <OpenWebUITools mode={connection?.mode ?? null} />
      </SettingList>
      <p className="settings-note">{t("assistant.security")}</p>
    </section>
  );
}

interface AssistantPrompt {
  language: string;
  prompt: string;
}

/** Branchement de l'Assist pas à pas, replié (déplié si le serveur ne répond pas) : l'adresse à
 * donner à l'intégration MCP de HA, l'agent de conversation, le prompt conseillé à copier. */
function SetupSteps({ mcpUrl, open }: { mcpUrl: string | null; open: boolean }) {
  const { language, t } = useI18n();
  const [prompt, setPrompt] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantPrompt>(`api/assistant/prompt?lang=${language}`, controller.signal)
      .then((found) => setPrompt(found.prompt))
      .catch(() => {
        if (!controller.signal.aborted) setPrompt(null);
      });
    return () => controller.abort();
  }, [language]);

  return (
    <details className="ui-setting-row settings-details voice-steps" open={open || undefined}>
      <summary>
        <span>
          <span className="ui-row-label">{t("assistant.setup")}</span>
          <span className="ui-row-help">{t("settings.voice.setup_help")}</span>
        </span>
        <Icon name="chevron-right" size={18} />
      </summary>
      <h4>{t("assistant.step1.title")}</h4>
      <p>{t("assistant.step1.help")}</p>
      {mcpUrl && (
        <p className="settings-actions">
          <code className="assistant-address">{mcpUrl}</code>
          <CopyButton text={mcpUrl} label={t("assistant.copy_address")} />
        </p>
      )}
      <h4>{t("assistant.step2.title")}</h4>
      <ul>
        <li>{t("assistant.step2.agent")}</li>
        <li>{t("assistant.step2.model")}</li>
        <li>{t("assistant.step2.api")}</li>
      </ul>
      <h4>{t("assistant.step3.title")}</h4>
      <p>{t("assistant.step3.help")}</p>
      {prompt === null && <p role="alert">{t("assistant.prompt_error")}</p>}
      {prompt && (
        <>
          <pre className="assistant-prompt" aria-label={t("assistant.prompt_label")}>
            {prompt}
          </pre>
          <CopyButton text={prompt} label={t("assistant.copy_prompt")} />
        </>
      )}
    </details>
  );
}

/** Intégrations MCP de Home Assistant : une ligne chacune, son état en pastille. */
function McpRows({ home }: { home: AssistantHome }) {
  const { t } = useI18n();
  if (home.mcp.length === 0) {
    return (
      <div className="ui-setting-row">
        <span>
          <span className="ui-row-label">{t("settings.voice.mcp")}</span>
          <span className="ui-row-help">{t("settings.voice.mcp_none")}</span>
        </span>
      </div>
    );
  }
  return (
    <>
      {home.mcp.map((entry, index) => {
        const state = mcpState(entry.state);
        return (
          <div key={`${entry.title}-${index}`} className="ui-setting-row">
            <span>
              <span className="ui-row-label">{t("settings.voice.mcp")}</span>
              <span className="ui-row-help">{entry.title}</span>
            </span>
            <span className="settings-pill" data-state={state}>
              {t(`settings.voice.mcp_states.${state}`)}
            </span>
          </div>
        );
      })}
    </>
  );
}

function HomeAssistantPart({
  home,
  pipeline,
  agent,
  save,
  onPipeline,
  onAgent,
  onSave,
}: {
  home: AssistantHome;
  pipeline: string;
  agent: string;
  save: Save;
  onPipeline: (id: string) => void;
  onAgent: (id: string) => void;
  onSave: () => void;
}) {
  const { t } = useI18n();
  const heading = <h3 className="home-summary-heading">{t("settings.voice.home")}</h3>;
  if (!home.connected || home.pipelines.length === 0) {
    return (
      <>
        {heading}
        <p role="status" className="settings-note">
          {t(home.connected ? "settings.voice.no_pipeline" : "settings.voice.not_connected")}
        </p>
      </>
    );
  }
  // Agent actuel que HA ne liste plus (intégration supprimée) : gardé dans la liste.
  const agents =
    agent && !home.agents.some((a) => a.id === agent) ? [...home.agents, { id: agent, name: agent }] : home.agents;
  return (
    <>
      {heading}
      <SettingList>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="voice-pipeline">
              {t("settings.voice.pipeline")}
            </label>
            <span className="ui-row-help">{t("settings.voice.pipeline_help")}</span>
          </span>
          <select id="voice-pipeline" value={pipeline} onChange={(event) => onPipeline(event.target.value)}>
            {home.pipelines.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="voice-agent">
              {t("settings.voice.agent")}
            </label>
            <span className="ui-row-help">{t("settings.voice.agent_help")}</span>
          </span>
          <select id="voice-agent" value={agent} onChange={(event) => onAgent(event.target.value)}>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="settings-foot">
          <span>
            {save === "saved" && (
              <span role="status" className="settings-ok">
                {t("settings.voice.saved")}
              </span>
            )}
            {(save === "invalid" || save === "failed") && <span role="alert">{t(`settings.voice.${save}`)}</span>}
          </span>
          <button
            type="button"
            className="ui-button ui-button-primary"
            disabled={save === "saving" || !agent}
            onClick={onSave}
          >
            {t("settings.save")}
          </button>
        </div>
      </SettingList>
    </>
  );
}
