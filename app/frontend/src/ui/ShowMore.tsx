// Longue liste repliée : les premiers éléments seulement, puis « Afficher les N autres » qui
// déplie le reste (« Afficher moins » le replie). Une longue liste ne cache pas la suite de la
// page (État de l'application, valeurs corrigées de Ma maison).

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";

/** Éléments montrés avant « Afficher les autres ». */
export const VISIBLE_ITEMS = 3;

/** Éléments à montrer et le bouton qui déplie ou replie (`null` si rien n'est caché). */
export function useShowMore<T>(items: T[], visible = VISIBLE_ITEMS, as: "div" | "li" = "div") {
  const { t } = useI18n();
  const [all, setAll] = useState(false);
  const hidden = items.length - visible;
  const Tag = as;
  const toggle =
    hidden > 0 ? (
      <Tag className="show-more">
        <button type="button" className="ui-button ui-button-quiet" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? t("ui.show_less") : t("ui.show_more", { count: hidden })}
        </button>
      </Tag>
    ) : null;
  return { shown: all ? items : items.slice(0, visible), toggle };
}
