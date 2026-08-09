import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives";
import { useIdentity } from "@/session/IdentityContext";
import { ROLE } from "@/lib/roles";
import { ApiError } from "@/api/client";
import { assignMembership, clearMembership, deleteCohortDefinition, updateCohortDefinition } from "@/api/services/cohorts";
import { CohortStateChip } from "./cohortBits";
import { CorrelationKeySelect, membersOf, unassignedPacks } from "./membership";
import { useActivePacks, useCohortDefinitions, useCohorts } from "./queries";
import type { ProcessPackManifest } from "@/api/types";
import { Kpi } from "./CohortsPage";

export function CohortDefinitionPage() {
  const { cohortDefId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { hasRole } = useIdentity();
  const isOwner = hasRole(ROLE.processOwner);

  const { data: definitions, isLoading: defsLoading } = useCohortDefinitions();
  const { data: packs } = useActivePacks();
  const { data: cohortList } = useCohorts();

  const def = definitions?.find((d) => d.cohort_def_id === cohortDefId);
  const members = useMemo(() => (def ? membersOf(def, packs) : []), [def, packs]);
  const candidates = useMemo(() => unassignedPacks(packs), [packs]);
  const instances = useMemo(
    () => (cohortList?.cohorts ?? []).filter((c) => c.cohort_def_id === cohortDefId),
    [cohortList, cohortDefId],
  );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["cohort-definitions"] });
    qc.invalidateQueries({ queryKey: ["active-packs"] });
    qc.invalidateQueries({ queryKey: ["cohorts", "all"] });
  };

  // --- inline edit of the definition's mutable fields (cohort_def_id stays immutable) ---
  type EditForm = { display_name: string; description: string; close_correlation_path: string; close_outcome_path: string; close_schema: string };
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function startEdit() {
    if (!def) return;
    setForm({
      display_name: def.display_name ?? "",
      description: def.description ?? "",
      close_correlation_path: def.close_correlation_path,
      close_outcome_path: def.close_outcome_path ?? "",
      close_schema: JSON.stringify(def.close_schema, null, 2),
    });
    setEditError(null);
    setEditing(true);
  }
  function cancelEdit() {
    setEditing(false);
    setForm(null);
    setEditError(null);
  }
  const setField = (k: keyof EditForm, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  async function onSave() {
    if (!form) return;
    let schema: Record<string, unknown>;
    try {
      schema = JSON.parse(form.close_schema);
    } catch {
      setEditError("Close schema is not valid JSON.");
      return;
    }
    if (!form.close_correlation_path.trim()) {
      setEditError("A correlation path is required.");
      return;
    }
    setSaving(true);
    try {
      await updateCohortDefinition(cohortDefId!, {
        display_name: form.display_name.trim() || null,
        description: form.description.trim() || null,
        close_schema: schema,
        close_correlation_path: form.close_correlation_path.trim(),
        close_outcome_path: form.close_outcome_path.trim() || null,
      });
      qc.invalidateQueries({ queryKey: ["cohort-definitions"] });
      toast.success(`Updated definition '${cohortDefId}'.`);
      setEditing(false);
      setForm(null);
      setEditError(null);
    } catch (err) {
      setEditError(err instanceof ApiError ? err.detailText : "Failed to update definition.");
    } finally {
      setSaving(false);
    }
  }

  async function onAssign(pack: ProcessPackManifest, correlation_key: string) {
    try {
      await assignMembership(pack.pack_key, pack.version, { cohort_def_id: cohortDefId!, correlation_key });
      refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detailText : "Failed to update membership.");
    }
  }
  async function onRemove(pack: ProcessPackManifest) {
    try {
      await clearMembership(pack.pack_key, pack.version);
      toast.success(`Removed ${pack.pack_key} from ${cohortDefId}.`);
      refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detailText : "Failed to remove member.");
    }
  }
  async function onDelete() {
    if (!window.confirm(`Delete cohort definition '${cohortDefId}'? Member packs keep running; only the definition is removed.`)) return;
    try {
      await deleteCohortDefinition(cohortDefId!);
      toast.success(`Deleted definition '${cohortDefId}'.`);
      qc.invalidateQueries({ queryKey: ["cohort-definitions"] });
      navigate("/cohorts?tab=definitions");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detailText : "Failed to delete definition.");
    }
  }

  const crumb = (
    <div className="mb-4 text-sm text-muted-foreground">
      <Link to="/cohorts?tab=definitions" className="inline-flex items-center gap-1 hover:text-foreground">
        <ArrowLeft className="size-4" /> Cohorts
      </Link>
      <span> / Definitions / <span className="font-mono text-foreground">{cohortDefId}</span></span>
    </div>
  );

  if (defsLoading) {
    return <>{crumb}<Skeleton className="h-8 w-64" /><Skeleton className="mt-4 h-48 w-full" /></>;
  }
  if (!def) {
    return (
      <>
        {crumb}
        <EmptyState title="Definition not found" description={`No cohort definition '${cohortDefId}' is registered.`} />
      </>
    );
  }

  return (
    <>
      {crumb}

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="font-mono text-xl font-semibold tracking-tight">{def.cohort_def_id}</h1>
          {def.display_name && <p className="text-sm text-muted-foreground">{def.display_name}</p>}
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="success" className="gap-1.5"><span className="size-1.5 rounded-full bg-success" /> Active</Badge>
          {isOwner && (editing ? (
            <>
              <Button size="sm" onClick={onSave} disabled={saving}><Save className="size-3.5" /> {saving ? "Saving…" : "Save"}</Button>
              <Button size="sm" variant="outline" onClick={cancelEdit}><X className="size-3.5" /> Cancel</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={startEdit}><Pencil className="size-3.5" /> Edit definition</Button>
              <Button size="sm" variant="outline" onClick={onDelete}><Trash2 className="size-3.5" /> Delete</Button>
            </>
          ))}
        </div>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Members" value={members.length} sub="packs assigned" />
        <Kpi label="Instances" value={instances.length} sub="observed" />
        <Kpi label="Closed" value={instances.filter((c) => c.state === "closed").length} sub="drained" tone="ok" />
        <Kpi label="Candidates" value={candidates.length} sub="unassigned packs" />
      </div>

      {/* Definition — read-only, or an inline editor in edit mode (owner-only) */}
      <Card className="mb-4">
        <CardHeader><CardTitle>Definition</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {editing && form ? (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="ed-name">Display name</Label>
                  <Input id="ed-name" value={form.display_name} onChange={(e) => setField("display_name", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ed-corr">Correlation path</Label>
                  <Input id="ed-corr" value={form.close_correlation_path} onChange={(e) => setField("close_correlation_path", e.target.value)} className="font-mono" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ed-desc">Description</Label>
                <Textarea id="ed-desc" value={form.description} onChange={(e) => setField("description", e.target.value)} className="min-h-[60px]" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ed-out">Outcome path <span className="text-muted-foreground">(optional)</span></Label>
                <Input id="ed-out" value={form.close_outcome_path} onChange={(e) => setField("close_outcome_path", e.target.value)} className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ed-schema">Close message schema (JSON Schema)</Label>
                <Textarea id="ed-schema" value={form.close_schema} onChange={(e) => setField("close_schema", e.target.value)} className="min-h-[160px] font-mono text-xs" spellCheck={false} />
                {instances.length > 0 && (
                  <p className="text-[11px] text-muted-foreground">
                    Schema / correlation-path changes affect <b>future</b> close-message recognition only — existing instances are unaffected.
                  </p>
                )}
              </div>
              {editError && <p className="text-sm text-danger">{editError}</p>}
            </>
          ) : (
            <>
              {def.description && <p className="text-muted-foreground">{def.description}</p>}
              <div className="grid gap-3 md:grid-cols-2">
                <Field k="Correlation path" v={def.close_correlation_path} />
                <Field k="Outcome path" v={def.close_outcome_path || "—"} />
              </div>
              <div>
                <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Close message schema (JSON Schema)</p>
                <pre className="max-h-72 overflow-auto rounded-md border border-border bg-surface/60 p-3 font-mono text-xs">
                  {JSON.stringify(def.close_schema, null, 2)}
                </pre>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Members (the relocated management) */}
      <Card className="mb-4">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Members</CardTitle>
          <span className="text-xs text-muted-foreground">{members.length} pack{members.length === 1 ? "" : "s"} assigned</span>
        </CardHeader>
        <CardContent>
          {instances.length > 0 && (
            <p className="mb-3 flex items-start gap-2 rounded-md border border-attention/40 bg-attention-muted/30 p-3 text-xs text-attention">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>Membership edits are <b>forward-only</b>: they change which future spawns join this cohort. The {instances.length} existing instance{instances.length === 1 ? "" : "s"} and their running/closed members are not re-homed or detached.</span>
            </p>
          )}

          {members.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No member packs yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Process pack</TableHead>
                  <TableHead>Correlation key</TableHead>
                  {isOwner && <TableHead />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((p) => (
                  <TableRow key={`${p.pack_key}@${p.version}`}>
                    <TableCell className="text-sm">
                      {p.pack_key} <span className="rounded border border-border px-1 text-[10px] text-muted-foreground">@{p.version}</span>
                    </TableCell>
                    <TableCell>
                      {isOwner ? (
                        <CorrelationKeySelect
                          packKey={p.pack_key}
                          version={p.version}
                          value={p.cohort_membership?.correlation_key ?? ""}
                          onChange={(k) => onAssign(p, k)}
                        />
                      ) : (
                        <span className="font-mono text-xs">{p.cohort_membership?.correlation_key}</span>
                      )}
                    </TableCell>
                    {isOwner && (
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" onClick={() => onRemove(p)}><X className="size-3.5" /> Remove</Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {isOwner && <AddMemberRow candidates={candidates} onAdd={onAssign} defaultKey={def.close_correlation_path} />}
        </CardContent>
      </Card>

      {/* Instances of this definition (read-only) */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Instances</CardTitle>
          <span className="text-xs text-muted-foreground">{instances.length} observed</span>
        </CardHeader>
        <CardContent>
          {instances.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No instances of this cohort yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Correlation</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Members</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {instances.map((c) => (
                  <TableRow
                    key={c.cohort_instance_id}
                    className="cursor-pointer"
                    tabIndex={0}
                    onClick={() => navigate(`/cohorts/${c.cohort_instance_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/cohorts/${c.cohort_instance_id}`)}
                  >
                    <TableCell className="font-mono text-sm text-foreground">{c.correlation_value || c.cohort_instance_id}</TableCell>
                    <TableCell><CohortStateChip state={c.state} /></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.member_count}</TableCell>
                    <TableCell className="text-sm">{c.outcome ? <span className="text-agent">{c.outcome}</span> : <span className="text-muted-foreground">—</span>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-md border border-border bg-surface/60 p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{k}</p>
      <p className="mt-1 font-mono text-sm">{v}</p>
    </div>
  );
}

/** The "+ Add pack" control: pick an unassigned active pack + a correlation key from its trigger fields. */
function AddMemberRow({
  candidates,
  onAdd,
  defaultKey,
}: {
  candidates: ProcessPackManifest[];
  onAdd: (pack: ProcessPackManifest, key: string) => void | Promise<void>;
  defaultKey: string;
}) {
  const [sel, setSel] = useState("");
  const [key, setKey] = useState("");
  const pack = candidates.find((p) => `${p.pack_key}@${p.version}` === sel);

  if (candidates.length === 0) {
    return <p className="mt-3 text-xs text-muted-foreground">No unassigned active packs to add.</p>;
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
      <span className="text-xs font-medium text-muted-foreground">+ Add pack:</span>
      <select
        aria-label="Add pack"
        value={sel}
        onChange={(e) => { setSel(e.target.value); setKey(""); }}
        className="h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <option value="">select active pack…</option>
        {candidates.map((p) => (
          <option key={`${p.pack_key}@${p.version}`} value={`${p.pack_key}@${p.version}`}>{p.pack_key}@{p.version}</option>
        ))}
      </select>
      {pack && (
        <>
          <CorrelationKeySelect packKey={pack.pack_key} version={pack.version} value={key} onChange={setKey}
            ariaLabel="New member correlation key" />
          <Button
            size="sm"
            disabled={!key.trim()}
            onClick={async () => { await onAdd(pack, key.trim() || defaultKey); setSel(""); setKey(""); }}
          >
            <Plus className="size-3.5" /> Add
          </Button>
        </>
      )}
    </div>
  );
}
