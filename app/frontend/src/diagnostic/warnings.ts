// Entités muettes, marquées dans le détail technique du diagnostic. La règle est celle du
// serveur (`ingestion.silent_entities`) : HA ne renvoie pas une valeur inchangée, seule une
// valeur figée suspecte (puissance non nulle, compteur d'un appareil en marche) est retenue.

import type { Diagnostic } from "./types";

/** Entités muettes à valeur figée suspecte, calculées par le serveur. */
export function silentEntities(diagnostic: Diagnostic): string[] {
  return diagnostic.silent ?? [];
}
