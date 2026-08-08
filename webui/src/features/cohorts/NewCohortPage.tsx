import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Check, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/api/client";
import { createCohortDefinition, assignMembership } from "@/api/services/cohorts";
import { useActivePacks, useTriggerFields } from "./queries";
import type { ProcessPackManifest } from "@/api/types";

const DEFAULT_SCHEMA = `{
  "type": "object",
  "required": ["event", "exception_id"],
  "properties": {
    "event":        { "const": "process_completed" },
    "exception_id": { "type": "string" },
    "outcome":      { "type": "string" }
  }
}`;

type Member = { pack_key: string; version: string; correlation_key: string };

function PackRow({
  pack,
  member,
  onToggle,
  onKey,
}: {
  pack: ProcessPackManifest;
  member: Member | undefined;
  onToggle: () => void;
  onKey: (key: string) => void;
}) {
  const { data: fields, isLoading } = useTriggerFields(pack.pack_key, pack.version);
  const assigned = member !== undefined;
  const hasFields = (fields?.length ?? 0) > 0;

  return (
    <TableRow>
      <TableCell className="w-8">{assigned ? <span className="text-success">●</span> : <span className="text-muted-foreground">○</span>}</TableCell>
      <TableCell className="text-sm">
        {pack.pack_key} <span className="rounded border border-border px-1 text-[10px] text-muted-foreground">@{pack.version}</span>
      </TableCell>
      <TableCell className="max-w-[220px] truncate font-mono text-xs text-muted-foreground">
        {isLoading ? <Skeleton className="h-4 w-24" /> : hasFields ? fields!.join(", ") : "—"}
      </TableCell>
      <TableCell>
        {!assigned ? (
          <span className="text-xs text-muted-foreground">—</span>
        ) : hasFields ? (
          <select
            value={member.correlation_key}
            onChange={(e) => onKey(e.target.value)}
            className="h-8 rounded-md border border-input bg-transparent px-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="" disabled>select field…</option>
            {fields!.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        ) : (
          <Input
            value={member.correlation_key}
            onChange={(e) => onKey(e.target.value)}
            placeholder="dotpath e.g. exception_id"
            className="h-8 w-40 font-mono text-xs"
          />
        )}
      </TableCell>
      <TableCell className="text-right">
        <Button size="sm" variant={assigned ? "secondary" : "outline"} onClick={onToggle}>
          {assigned ? <><Check className="size-3.5" /> Added</> : <><Plus className="size-3.5" /> Add</>}
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function NewCohortPage() {
  const navigate = useNavigate();
  const { data: packs, isLoading: packsLoading } = useActivePacks();

  const [cohortDefId, setCohortDefId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [closeSchema, setCloseSchema] = useState(DEFAULT_SCHEMA);
  const [corrPath, setCorrPath] = useState("exception_id");
  const [outcomePath, setOutcomePath] = useState("outcome");
  const [members, setMembers] = useState<Record<string, Member>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const keyOf = (p: ProcessPackManifest) => `${p.pack_key}@${p.version}`;
  const assignedCount = Object.keys(members).length;

  function toggle(p: ProcessPackManifest, firstField?: string) {
    const k = keyOf(p);
    setMembers((prev) => {
      const next = { ...prev };
      if (next[k]) delete next[k];
      else next[k] = { pack_key: p.pack_key, version: p.version, correlation_key: firstField ?? corrPath };
      return next;
    });
  }
  function setKey(p: ProcessPackManifest, correlation_key: string) {
    const k = keyOf(p);
    setMembers((prev) => ({ ...prev, [k]: { pack_key: p.pack_key, version: p.version, correlation_key } }));
  }

  function validate(): { schema: Record<string, unknown> } | null {
    if (!cohortDefId.trim()) { setError("Cohort id is required."); return null; }
    let schema: Record<string, unknown>;
    try {
      schema = JSON.parse(closeSchema);
    } catch {
      setError("Close message schema is not valid JSON.");
      return null;
    }
    if (!corrPath.trim()) { setError("A correlation path is required."); return null; }
    for (const [k, m] of Object.entries(members)) {
      if (!m.correlation_key.trim()) { setError(`Assigned pack ${k} needs a correlation key.`); return null; }
    }
    setError(null);
    return { schema };
  }

  async function onSubmit() {
    const ok = validate();
    if (!ok) return;
    setSubmitting(true);
    try {
      await createCohortDefinition({
        cohort_def_id: cohortDefId.trim(),
        display_name: displayName.trim() || null,
        description: description.trim() || null,
        close_schema: ok.schema,
        close_correlation_path: corrPath.trim(),
        close_outcome_path: outcomePath.trim() || null,
      });
      const assignments = Object.values(members);
      for (const m of assignments) {
        await assignMembership(m.pack_key, m.version, { cohort_def_id: cohortDefId.trim(), correlation_key: m.correlation_key.trim() });
      }
      toast.success(`Cohort '${cohortDefId.trim()}' registered${assignments.length ? ` with ${assignments.length} member${assignments.length === 1 ? "" : "s"}` : ""}.`);
      navigate("/cohorts");
    } catch (err) {
      setError(err instanceof ApiError ? err.detailText : "Failed to register cohort.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="mb-2 text-sm text-muted-foreground">
        <Link to="/cohorts" className="hover:text-foreground">Cohorts</Link> / New cohort
      </div>
      <h1 className="mb-5 text-xl font-semibold tracking-tight">New cohort definition</h1>

      <Card className="mb-4">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Definition</CardTitle>
          <span className="text-xs text-muted-foreground">registered once · like onboarding a pack</span>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="coh-id">Cohort id</Label>
              <Input id="coh-id" value={cohortDefId} onChange={(e) => setCohortDefId(e.target.value)} placeholder="wire_transfer_cohort" />
              <p className="text-[11px] text-muted-foreground">Internal Amendia identifier — never shared with the external orchestrator.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="coh-name">Display name</Label>
              <Input id="coh-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Wire transfer — cross-system case" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="coh-desc">Description</Label>
            <Input id="coh-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="coh-schema">Close message schema (JSON Schema)</Label>
            <p className="text-[11px] text-muted-foreground">The orchestrator emits this when the overall process ends. Amendia recognises it by schema and closes the cohort by the correlation value alone.</p>
            <Textarea id="coh-schema" value={closeSchema} onChange={(e) => setCloseSchema(e.target.value)} className="min-h-[140px] font-mono text-xs" spellCheck={false} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="coh-corr">Correlation path → cohort key</Label>
              <Input id="coh-corr" value={corrPath} onChange={(e) => setCorrPath(e.target.value)} className="font-mono" />
              <p className="text-[11px] text-muted-foreground">Dotpath into the close message → the value identifying the cohort instance.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="coh-out">Outcome path <span className="text-muted-foreground">(optional)</span></Label>
              <Input id="coh-out" value={outcomePath} onChange={(e) => setOutcomePath(e.target.value)} className="font-mono" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-4">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Members</CardTitle>
          <span className="text-xs text-muted-foreground">assign active process packs · {assignedCount} assigned</span>
        </CardHeader>
        <CardContent>
          <p className="mb-3 rounded-md border border-dashed border-border bg-surface/50 p-3 text-xs text-muted-foreground">
            Each member maps <span className="font-medium text-foreground">its own</span> trigger field to the cohort's correlation key (packs triage on different trigger schemas), so you set a correlation key per pack. A pack with no membership stays a normal standalone process.
          </p>
          {packsLoading ? (
            <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
          ) : (packs?.length ?? 0) === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No active packs to assign. Onboard and activate a pack first.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-8" />
                  <TableHead>Process pack</TableHead>
                  <TableHead>Trigger fields</TableHead>
                  <TableHead>Correlation key</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {packs!.map((p) => (
                  <PackRowConnected key={keyOf(p)} pack={p} member={members[keyOf(p)]} onToggle={toggle} onKey={setKey} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {error && <p className="mb-3 text-sm text-danger">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => navigate("/cohorts")}>Cancel</Button>
        <Button onClick={onSubmit} disabled={submitting}>{submitting ? "Registering…" : "Register cohort"}</Button>
      </div>
    </>
  );
}

/** Bridges PackRow's per-pack callbacks to the parent members map, and defaults the key to the pack's first trigger field on add. */
function PackRowConnected({
  pack,
  member,
  onToggle,
  onKey,
}: {
  pack: ProcessPackManifest;
  member: Member | undefined;
  onToggle: (p: ProcessPackManifest, firstField?: string) => void;
  onKey: (p: ProcessPackManifest, key: string) => void;
}) {
  const { data: fields } = useTriggerFields(pack.pack_key, pack.version);
  return (
    <PackRow
      pack={pack}
      member={member}
      onToggle={() => onToggle(pack, fields?.[0])}
      onKey={(k) => onKey(pack, k)}
    />
  );
}
