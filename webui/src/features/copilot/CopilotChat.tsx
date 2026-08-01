// features/copilot/CopilotChat.tsx — refine by conversation. The business user types a plain-language
// adjustment; the copilot interprets it, applies it deterministically, and replies in plain language.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Send, Sparkles, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { copilotChat, type ChangeDiff, type OnboardingSession } from "@/api/services/registry";
import { describeChangeField, friendlyReply, humanizeElementId } from "./humanize";

function changeLine(c: ChangeDiff): string {
  return `${describeChangeField(c.field)} for “${humanizeElementId(c.element_id)}”`;
}

export function CopilotChat({ session, onUpdated }: {
  session: OnboardingSession;
  onUpdated: (s: OnboardingSession) => void;
}) {
  const [draft, setDraft] = useState("");
  const [clarify, setClarify] = useState<{ message: string; reply: string } | null>(null);
  const [lastChanges, setLastChanges] = useState<ChangeDiff[]>([]);

  const chat = useMutation({
    mutationFn: (message: string) => copilotChat(session.session_id, { message }),
    onSuccess: (resp, message) => {
      setDraft("");
      setLastChanges(resp.changes ?? []);
      if (resp.needs_clarification) {
        setClarify({ message, reply: resp.reply });      // not persisted server-side — show it transiently
      } else {
        setClarify(null);
        onUpdated(resp.session);                          // the transcript now carries the new turn
      }
    },
  });

  const turns = session.conversation ?? [];

  function send() {
    const m = draft.trim();
    if (m && !chat.isPending) chat.mutate(m);
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Sparkles className="size-4 text-agent" />
        <span className="text-sm font-medium">Refine with the copilot</span>
      </div>

      <div className="flex-1 space-y-3 overflow-auto p-4">
        {turns.length === 0 && !clarify && (
          <p className="text-sm text-muted-foreground">
            Tell the copilot what to change in plain language — e.g. “a manager should approve payments, not the
            cashier”. It updates the design and re-checks it's safe to run.
          </p>
        )}
        {turns.map((t, i) => (
          <div key={i} className="space-y-1.5">
            <div className="ml-8 rounded-lg bg-accent px-3 py-2 text-sm text-accent-foreground">{t.message}</div>
            <div className="mr-8 flex gap-2">
              <Sparkles className="mt-1 size-4 shrink-0 text-agent" />
              <p className="text-sm text-muted-foreground">{friendlyReply(t.reply)}</p>
            </div>
          </div>
        ))}

        {clarify && (
          <div className="space-y-1.5">
            <div className="ml-8 rounded-lg bg-accent px-3 py-2 text-sm text-accent-foreground">{clarify.message}</div>
            <div className="mr-8 flex gap-2 text-sm text-muted-foreground">
              <HelpCircle className="mt-0.5 size-4 shrink-0 text-agent" />
              <p>{friendlyReply(clarify.reply)}</p>
            </div>
          </div>
        )}

        {!clarify && lastChanges.length > 0 && (
          <div className="mr-8 rounded-md border border-agent/30 bg-agent-muted/20 p-2.5 text-xs">
            <span className="font-medium text-agent">Changed:</span>{" "}
            <span className="text-muted-foreground">{lastChanges.map(changeLine).join("; ")}.</span>
          </div>
        )}
      </div>

      <div className="border-t border-border p-3">
        <Textarea
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }}
          placeholder="Describe a change…"
          aria-label="Refine message"
          className="mb-2 resize-none text-sm"
        />
        <div className="flex justify-end">
          <Button size="sm" onClick={send} disabled={!draft.trim() || chat.isPending}>
            <Send className="size-4" /> {chat.isPending ? "Thinking…" : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}
