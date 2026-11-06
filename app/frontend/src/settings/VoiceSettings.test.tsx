// Sous-page « Assistant vocal » des Réglages : état du serveur MCP, configuration lue dans
// Home Assistant, choix de l'assistant préféré et de son agent de conversation.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import VoiceSettings from "./VoiceSettings";

const HOME = {
  connected: true,
  mcp: [{ title: "WattSlot", state: "loaded" }],
  pipelines: [
    { id: "p1", name: "Home Assistant", conversation_engine: "conversation.home_assistant" },
    { id: "p2", name: "Avec LLM", conversation_engine: "conversation.llm" },
  ],
  preferred_pipeline: "p1",
  agents: [
    { id: "conversation.home_assistant", name: "Home Assistant" },
    { id: "conversation.llm", name: "Modèle de langue" },
  ],
};

const PROMPT = "Tu es l'assistant énergie d'une maison avec des panneaux solaires.";

type Calls = { url: string; method: string; body: unknown }[];

function mockApi(home: unknown = HOME, put: (body: unknown) => Response = () => Response.json(HOME)): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, method, body });
    if (url === "api/assistant/connection" && method === "PUT") {
      const { mcp_url } = body as { mcp_url: string | null };
      return mcp_url?.startsWith("http")
        ? Response.json({ mode: "standalone", mcp_url, saved: true })
        : mcp_url === null
          ? Response.json({ mode: "standalone", mcp_url: null, saved: false })
          : Response.json({ detail: "invalid_url" }, { status: 422 });
    }
    if (url === "api/assistant/connection") return Response.json({ mode: "standalone", mcp_url: null });
    if (url === "api/assistant/home" && method === "PUT") return put(body);
    if (url === "api/assistant/home") return Response.json(home);
    if (url.startsWith("api/assistant/prompt")) return Response.json({ language: "fr", prompt: PROMPT });
    if (url === "mcp") {
      const { id, method: rpc } = body as { id: number; method: string };
      const result = rpc === "tools/list" ? { tools: new Array(9).fill({ name: "x" }) } : { serverInfo: {} };
      return Response.json({ jsonrpc: "2.0", id, result });
    }
    return new Response(null, { status: 404 });
  });
  return calls;
}

function renderPage() {
  render(
    <I18nProvider>
      <VoiceSettings />
    </I18nProvider>,
  );
}

describe("sous-page « Assistant vocal »", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("montre l'état, l'adresse du serveur et la configuration de Home Assistant", async () => {
    mockApi();
    renderPage();

    expect(await screen.findByText("Le serveur MCP répond : 9 outils.")).toBeInTheDocument();
    // L'adresse : sur sa ligne, et reprise dans le pas à pas.
    expect(screen.getAllByText(`${window.location.origin}/mcp`)).toHaveLength(2);
    expect(await screen.findByText("Intégration MCP dans Home Assistant")).toBeInTheDocument();
    expect(screen.getByText("WattSlot")).toBeInTheDocument();
    expect(screen.getByText("chargée")).toBeInTheDocument();
    expect(screen.getByLabelText("Assistant préféré")).toHaveValue("p1");
    expect(screen.getByLabelText("Agent de conversation")).toHaveValue("conversation.home_assistant");
  });

  it("le pas à pas, replié, donne l'adresse et le prompt conseillé à copier", async () => {
    mockApi();
    renderPage();
    const user = userEvent.setup();

    await screen.findByText("Le serveur MCP répond : 9 outils.");
    const steps = screen.getByText("Brancher l'Assist pas à pas").closest("details") as HTMLDetailsElement;
    expect(steps.open).toBe(false); // serveur vérifié : replié
    expect(await within(steps).findByText(PROMPT)).toBeInTheDocument();
    expect(within(steps).getByText(`${window.location.origin}/mcp`)).toBeInTheDocument();
    await user.click(within(steps).getByText("Brancher l'Assist pas à pas"));
    await user.click(within(steps).getByRole("button", { name: "Copier le prompt" }));
    expect(await navigator.clipboard.readText()).toBe(PROMPT); // presse-papiers de user-event
  });

  it("retient l'adresse interne vue du réseau local, et la laisse corriger", async () => {
    const calls = mockApi();
    renderPage();
    const user = userEvent.setup();

    // Page ouverte depuis le réseau local (localhost) : son adresse est retenue.
    expect(await screen.findAllByText(`${window.location.origin}/mcp`)).toHaveLength(2);
    expect(calls.find((call) => call.method === "PUT" && call.url === "api/assistant/connection")?.body).toEqual({
      mcp_url: `${window.location.origin}/mcp`,
    });

    await user.click(screen.getByRole("button", { name: "Modifier" }));
    const field = screen.getByLabelText("Adresse interne du serveur MCP");
    const form = within(field.closest("form")!);
    await user.clear(field);
    await user.type(field, "192.0.2.10:8100");
    await user.click(form.getByRole("button", { name: "Enregistrer" }));
    expect(await form.findByRole("alert")).toHaveTextContent("Adresse attendue");
    await user.clear(field);
    await user.type(field, "http://192.0.2.10:8100/mcp");
    await user.click(form.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findAllByText("http://192.0.2.10:8100/mcp")).toHaveLength(2);
  });

  it("change l'agent de l'assistant préféré dans Home Assistant", async () => {
    const calls = mockApi(HOME, (body) =>
      Response.json({
        ...HOME,
        pipelines: [{ ...HOME.pipelines[0], conversation_engine: "conversation.llm" }, HOME.pipelines[1]],
        preferred_pipeline: (body as { pipeline_id: string }).pipeline_id,
      }),
    );
    renderPage();
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Agent de conversation"), "conversation.llm");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Assistant modifié dans Home Assistant.")).toBeInTheDocument();
    expect(calls.find((call) => call.method === "PUT" && call.url === "api/assistant/home")?.body).toEqual({
      pipeline_id: "p1",
      conversation_engine: "conversation.llm",
    });
    expect(screen.getByLabelText("Agent de conversation")).toHaveValue("conversation.llm");
  });

  it("un autre assistant reprend son propre agent", async () => {
    mockApi();
    renderPage();
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Assistant préféré"), "p2");

    expect(screen.getByLabelText("Agent de conversation")).toHaveValue("conversation.llm");
  });

  it("dit quand Home Assistant refuse la modification", async () => {
    mockApi(HOME, () => Response.json({ detail: "refusé" }, { status: 502 }));
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Home Assistant a refusé la modification");
  });

  it("sans Home Assistant : ni intégration ni choix", async () => {
    mockApi({ connected: false, mcp: [], pipelines: [], preferred_pipeline: null, agents: [] });
    renderPage();

    expect(await screen.findByText(/Home Assistant n'est pas connecté/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Agent de conversation")).not.toBeInTheDocument();
  });
});
