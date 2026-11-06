import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { LANGUAGES } from "../i18n/translate";
import AssistantScreen from "./AssistantScreen";

const PROMPT = "Tu es l'assistant énergie d'une maison avec des panneaux solaires.";

function mockApi({ addon = false, mcp = true }: { addon?: boolean; mcp?: boolean } = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/assistant/connection") {
      return Response.json(
        addon
          ? { mode: "addon", mcp_url: "http://a0d7b954-wattslot:8100/mcp" }
          : { mode: "standalone", mcp_url: null },
      );
    }
    if (url.startsWith("api/assistant/prompt")) return Response.json({ language: "fr", prompt: PROMPT });
    if (url === "mcp" && mcp) {
      const body = JSON.parse(String(init?.body)) as { id: number; method: string };
      const result = body.method === "tools/list" ? { tools: new Array(9).fill({ name: "x" }) } : { serverInfo: {} };
      return Response.json({ jsonrpc: "2.0", id: body.id, result });
    }
    return new Response(null, { status: 503 });
  });
}

function renderScreen() {
  render(
    <I18nProvider>
      <AssistantScreen />
    </I18nProvider>,
  );
}

describe("page « Assistant »", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("ne montre que la discussion : le branchement est dans les Réglages", async () => {
    mockApi();
    renderScreen();

    expect(await screen.findByLabelText("Votre message")).toBeInTheDocument();
    expect(screen.queryByText("Brancher l'Assist pas à pas")).not.toBeInTheDocument();
    expect(screen.queryByText(PROMPT)).not.toBeInTheDocument();
  });

  it("les questions d'exemple, par thème, remplissent la zone de saisie du chat", async () => {
    mockApi();
    renderScreen();
    const user = userEvent.setup();

    const today = await screen.findByRole("list", { name: "Aujourd'hui" });
    expect(within(today).getAllByRole("button")).toHaveLength(5);
    expect(screen.getByRole("list", { name: "Demandes et état" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Quelles sont mes demandes en cours ?" }));

    const input = screen.getByLabelText("Votre message");
    expect(input).toHaveValue("Quelles sont mes demandes en cours ?");
    expect(input).toHaveFocus();
  });

  it.each(LANGUAGES)("%s : aucune clé brute", async (language) => {
    window.localStorage.setItem("wattslot.language", language);
    mockApi();
    renderScreen();
    await screen.findByRole("textbox");
    // Le catalogue chargé à la demande est lu : plus de texte de secours en anglais à attendre.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.body.textContent ?? "").not.toMatch(/\bassistant\.[a-z_.]+/);
  });
});
