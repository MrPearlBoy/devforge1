import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { formatTime, relativeTime } from "../hooks/useApi";
import type { AgentSpec, ChatMessage, ProposedChange } from "../types/api";
import { Card, ErrorNote, Loading, MockBadge } from "../components/ui";

/**
 * Conversation with a specialist agent. Code proposals are never applied here: they open an
 * approval gate that the human decides on the Approvals tab.
 */
export function ChatPage() {
  const { projectId = "" } = useParams();
  const [params] = useSearchParams();
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [agentKey, setAgentKey] = useState(params.get("agent") || "developer");
  const [threadId, setThreadId] = useState("default");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [allowProposals, setAllowProposals] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastApproval, setLastApproval] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api.agents().then(setAgents).catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api
      .chatHistory(projectId, threadId)
      .then((rows) => !cancelled && setMessages(rows))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : ""));
    return () => {
      cancelled = true;
    };
  }, [projectId, threadId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setBusy(true);
    setError("");
    const human: ChatMessage = {
      id: `local-${Date.now()}`,
      project_id: projectId,
      agent_key: agentKey,
      thread_id: threadId,
      role: "USER",
      content: input,
      user_id: null,
      execution_id: null,
      meta: {},
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, human]);
    const message = input;
    setInput("");
    try {
      const reply = await api.chat(projectId, {
        message,
        agent_key: agentKey,
        thread_id: threadId,
        allow_code_proposals: allowProposals,
      });
      setLastApproval(reply.approval_id);
      const rows = await api.chatHistory(projectId, threadId);
      setMessages(rows);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The agent did not answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <Card
        title="Agent conversation"
        subtitle="Ask for clarifications, request a change, or discuss a security finding"
        actions={
          <select
            className="input w-48 py-1.5 text-xs"
            value={agentKey}
            onChange={(event) => setAgentKey(event.target.value)}
          >
            {(agents.length ? agents : [{ key: "developer", name: "Developer Agent" } as AgentSpec]).map(
              (agent) => (
                <option key={agent.key} value={agent.key}>
                  {agent.name}
                </option>
              ),
            )}
          </select>
        }
      >
        <div className="flex h-[26rem] flex-col gap-3 overflow-y-auto rounded-lg bg-slate-50 p-3">
          {messages.length === 0 && (
            <p className="m-auto max-w-sm text-center text-xs text-slate-500">
              No messages yet. Try: “Add a priority field to tasks and a filter for it.” The
              Developer Agent will reply with a proposal you can approve.
            </p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {busy && <Loading label={`${agentKey} agent is thinking…`} />}
          <div ref={bottom} />
        </div>

        <ErrorNote message={error} />
        {lastApproval && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
            A code proposal was filed and is waiting for your decision on the{" "}
            <Link className="font-semibold underline" to={`/projects/${projectId}/approvals`}>
              Approvals
            </Link>{" "}
            tab. Chat can never write to the workspace on its own.
          </p>
        )}

        <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={send}>
          <div className="min-w-[16rem] flex-1">
            <textarea
              className="input"
              rows={2}
              placeholder="Write to the agent…"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send(event);
                }
              }}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2 text-[11px] text-slate-600">
              <input
                type="checkbox"
                checked={allowProposals}
                onChange={(event) => setAllowProposals(event.target.checked)}
              />
              allow code proposals
            </label>
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send"}
            </button>
          </div>
        </form>
      </Card>

      <div className="space-y-4">
        <Card title="Thread" subtitle="Conversations are stored per project and agent">
          <label className="label" htmlFor="thread">
            Thread id
          </label>
          <input
            id="thread"
            className="input"
            value={threadId}
            onChange={(event) => setThreadId(event.target.value || "default")}
          />
          <p className="mt-2 text-[11px] text-slate-500">
            {messages.length} message(s) in this thread.
          </p>
        </Card>

        <Card title="Who answers" subtitle="Pick the specialist that fits your question">
          <ul className="space-y-2 text-xs">
            {agents.map((agent) => (
              <li key={agent.key}>
                <button
                  className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                    agentKey === agent.key
                      ? "border-forge-400 bg-forge-50/70"
                      : "border-slate-200 hover:border-forge-300"
                  }`}
                  onClick={() => setAgentKey(agent.key)}
                >
                  <p className="font-semibold text-slate-800">{agent.name}</p>
                  <p className="text-[11px] text-slate-500">{agent.role}</p>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "USER";
  const proposals = (message.meta?.proposed_changes as ProposedChange[]) || [];
  const mode = (message.meta?.mode as string) || "";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-xs shadow-sm ${
          isUser ? "bg-forge-600 text-white" : "bg-white text-slate-800 ring-1 ring-slate-200"
        }`}
      >
        <div className="mb-1 flex items-center gap-2 text-[10px] opacity-80">
          <span className="font-semibold">{isUser ? "You" : message.agent_key || "agent"}</span>
          <span>· {formatTime(message.created_at)}</span>
          {!isUser && mode && <MockBadge mode={mode} />}
        </div>
        <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>

        {proposals.length > 0 && (
          <div className="mt-2 rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Proposed changes
            </p>
            <ul className="space-y-1">
              {proposals.map((change) => (
                <li key={change.path} className="font-mono text-[11px] text-slate-700">
                  {change.op === "create" ? "+" : change.op === "delete" ? "-" : "~"} {change.path}
                  <span className="ml-2 text-[10px] text-slate-500">
                    +{change.additions} -{change.deletions}
                  </span>
                </li>
              ))}
            </ul>
            {(message.meta?.approval_id as string) && (
              <p className="mt-1 text-[10px] font-medium text-amber-700">
                awaiting approval · filed {relativeTime(message.created_at)}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
