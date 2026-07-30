// features/copilot/TriggerInput.tsx — "The event that starts this process". The user pastes a sample event OR a
// JSON Schema; we validate the JSON inline and show a parsed-fields preview. Feeds generate.trigger.
import { useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { parseTriggerFields } from "./triggerParse";

export interface TriggerValue {
  text: string;
  raw: Record<string, unknown> | null;   // the parsed JSON (null when empty/invalid)
  fields: Record<string, string>;          // field → jsonType, for the triage builder
}

export const EMPTY_TRIGGER: TriggerValue = { text: "", raw: null, fields: {} };

export function TriggerInput({ value, onChange }: {
  value: TriggerValue;
  onChange: (v: TriggerValue) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  function onText(text: string) {
    if (!text.trim()) {
      setError(null);
      onChange({ text, raw: null, fields: {} });
      return;
    }
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError("The event must be a JSON object.");
        onChange({ text, raw: null, fields: {} });
        return;
      }
      setError(null);
      onChange({ text, raw: parsed as Record<string, unknown>, fields: parseTriggerFields(parsed as Record<string, unknown>) });
    } catch {
      setError("That isn't valid JSON — check for a missing comma or quote.");
      onChange({ text, raw: null, fields: {} });
    }
  }

  const fields = Object.entries(value.fields);
  return (
    <div>
      <h3 className="text-sm font-medium">The event that starts this process</h3>
      <p className="mb-2 mt-0.5 text-xs text-muted-foreground">
        Paste a sample of the event that kicks this process off (or its JSON Schema). The copilot uses it as the
        contract for what arrives.
      </p>
      <Textarea
        rows={7}
        value={value.text}
        onChange={(e) => onText(e.target.value)}
        placeholder={'{\n  "event_type": "request.created",\n  "region": "EU",\n  "tags": ["expedite"]\n}'}
        aria-label="Trigger event or schema"
        className={`resize-y font-mono text-xs ${error ? "border-danger/60" : ""}`}
      />
      {error && (
        <p className="mt-1 flex items-center gap-1 text-xs text-danger"><AlertTriangle className="size-3.5" /> {error}</p>
      )}
      {fields.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <CheckCircle2 className="size-3.5 text-success" />
          <span className="text-xs text-muted-foreground">Fields:</span>
          {fields.map(([f, t]) => (
            <Badge key={f} variant="outline" className="font-mono text-[10px]">{f} <span className="ml-1 opacity-60">{t}</span></Badge>
          ))}
        </div>
      )}
    </div>
  );
}
