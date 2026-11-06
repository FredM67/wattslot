// Rapport anonymisé à joindre à un ticket (lot 4.8, point n° 7) : préparé par l'application
// (/api/diagnostic/report), montré en entier avant d'être téléchargé. Il ne contient ni nom
// d'équipement, ni identifiant d'entité, ni position.

import { useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

type State = { status: "idle" | "loading" | "error" } | { status: "ready"; text: string };

export default function ReportSection() {
  const { t } = useI18n();
  const [state, setState] = useState<State>({ status: "idle" });

  const prepare = async () => {
    setState({ status: "loading" });
    try {
      const report = await getJson<unknown>("api/diagnostic/report");
      setState({ status: "ready", text: JSON.stringify(report, null, 2) });
    } catch {
      setState({ status: "error" });
    }
  };

  const download = (text: string) => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `wattslot-rapport-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section aria-labelledby="report-title">
      <h3 id="report-title" className="home-summary-heading">
        {t("report.title")}
      </h3>
      <div className="ui-setting-list">
        <div className="ui-setting-row">
          <span className="ui-row-help report-intro">{t("report.intro")}</span>
          <button type="button" disabled={state.status === "loading"} onClick={() => void prepare()}>
            {t("report.prepare")}
          </button>
        </div>
        {state.status === "error" && (
          <p role="alert" className="settings-foot">
            {t("report.error")}
          </p>
        )}
        {state.status === "ready" && (
          <div className="report-preview">
            <p className="ui-row-help">{t("report.preview")}</p>
            <pre aria-label={t("report.preview_label")}>{state.text}</pre>
            <div className="settings-foot">
              <span />
              <button type="button" className="ui-button ui-button-primary" onClick={() => download(state.text)}>
                {t("report.download")}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
