// Section « Langue et affichage » des réglages (lots 6b.1 et 6b.2), en listes comme les autres
// sous-pages : langue de l'interface et devise, thème, légendes des courbes. Langue, thème et
// légendes sont gardés sur cet appareil et appliqués tout de suite, sans « Enregistrer ».
// Devise de la maison (lot 7.3) : enregistrée par le serveur, pour tous les appareils.

import { useState } from "react";

import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES, reviewed, SUPPORTED_LANGUAGES } from "../i18n/translate";
import { useChartLegends } from "../plan/legends";
import { useTheme } from "../theme/theme";
import { SettingList } from "../ui/SettingRow";
import Switch from "../ui/Switch";
import ThemePicker from "../ui/ThemePicker";

export default function AppearanceSection() {
  const { language, setLanguage, t } = useI18n();
  const [theme, setTheme] = useTheme();
  const [legends, setLegends] = useChartLegends();
  return (
    <>
      <h3 className="home-summary-heading">{t("settings.appearance.region_title")}</h3>
      <SettingList>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="app-language">
              {t("app.language")}
            </label>
            <span className="ui-row-help">{t("settings.appearance.language_help")}</span>
          </span>
          <select
            id="app-language"
            value={language}
            onChange={(event) => setLanguage(event.target.value as typeof language)}
          >
            {SUPPORTED_LANGUAGES.map((code) => (
              <option key={code} value={code}>
                {reviewed(code) ? LANGUAGE_NAMES[code] : t("app.to_review", { name: LANGUAGE_NAMES[code] })}
              </option>
            ))}
          </select>
        </div>
        <CurrencyRow />
      </SettingList>

      <ThemePicker value={theme} onChange={setTheme} />
      <p className="settings-note">{t("settings.appearance.help")}</p>

      <h3 className="home-summary-heading">{t("settings.appearance.charts_title")}</h3>
      <SettingList>
        <Switch
          label={t("settings.appearance.legends")}
          description={t("settings.appearance.legends_help")}
          checked={legends}
          onChange={setLegends}
        />
      </SettingList>
    </>
  );
}

function CurrencyRow() {
  const { language, t } = useI18n();
  const { state, save } = useCurrency();
  const [failed, setFailed] = useState(false);
  if (state === null) return null;
  const name = (code: string) => new Intl.DisplayNames(language, { type: "currency" }).of(code) ?? code;
  const choices = state.code && !state.choices.includes(state.code) ? [...state.choices, state.code] : state.choices;
  const change = (value: string) => {
    setFailed(false);
    save(value === "" ? null : value).catch(() => setFailed(true));
  };
  return (
    <div className="ui-setting-row">
      <span>
        <label className="ui-row-label" htmlFor="app-currency">
          {t("settings.currency.label")}
        </label>
        <span className="ui-row-help">{t("settings.currency.hint")}</span>
        {failed && (
          <span role="alert" className="ui-row-help settings-danger">
            {t("settings.currency.failed")}
          </span>
        )}
      </span>
      <select id="app-currency" value={state.code ?? ""} onChange={(event) => change(event.target.value)}>
        <option value="">
          {state.home_assistant
            ? t("settings.currency.automatic", { name: name(state.home_assistant) })
            : t("settings.currency.automatic_default", { name: name("EUR") })}
        </option>
        {choices.map((code) => (
          <option key={code} value={code}>
            {name(code)} ({code})
          </option>
        ))}
      </select>
    </div>
  );
}
