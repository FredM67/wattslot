// Page « Assistant » (lot 6.3) : la discussion avec l'assistant, et ses questions d'exemple.
// Le branchement de l'Assist de Home Assistant (état du serveur MCP, pas à pas, prompt conseillé)
// est dans Réglages › Assistant vocal ; « Mes demandes » est dans Planning, à côté du plan.

import { useState } from "react";

import ChatCard from "./ChatCard";

const CHAT_INPUT = "assistant-chat-input";

export default function AssistantScreen() {
  const [draft, setDraft] = useState("");
  return (
    <div className="assistant">
      <ChatCard inputId={CHAT_INPUT} draft={draft} onDraft={setDraft} />
    </div>
  );
}
