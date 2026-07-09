import { describe, it, expect, vi, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { synthTask, synthException, synthInstanceDetail, synthPack, TEST_SCHEMA } from "@/test/fixtures";

const R = SERVICE_BASE.runtime;
const REG = SERVICE_BASE.registry;
const STUB = SERVICE_BASE.stub;

/** Ancillary handlers the task context rail hits, so no request is un-stubbed. */
function railHandlers() {
  return [
    http.get(`${STUB}/exceptions/:id`, () => HttpResponse.json(synthException())),
    http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
    http.get(`${REG}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: TEST_SCHEMA })),
    http.get(`${R}/instances/:id`, () => HttpResponse.json(synthInstanceDetail())),
  ];
}

describe("Task inbox", () => {
  it("renders open tasks across the four HITL modes", async () => {
    server.use(
      http.get(`${R}/hitl-tasks`, () =>
        HttpResponse.json([
          synthTask({ task_id: "t1", title: "Review gate", hitl_mode: "review_after" }),
          synthTask({ task_id: "t2", title: "Approve-result gate", hitl_mode: "approve_result", role: "role.payments.ops_approver", allowed_decisions: ["approve", "reject"] }),
          synthTask({ task_id: "t3", title: "Authorize gate", hitl_mode: "approve_actions", role: "role.payments.ops_approver", allowed_decisions: ["approve", "reject"] }),
          synthTask({ task_id: "t4", title: "Manual gate", hitl_mode: "manual", allowed_decisions: ["complete", "escalate"] }),
        ]),
      ),
    );
    renderApp("/inbox", "approver-1");
    expect(await screen.findByText("Review gate")).toBeInTheDocument();
    expect(await screen.findByText("Approve-result gate")).toBeInTheDocument();
    expect(await screen.findByText("Authorize gate")).toBeInTheDocument();
    expect(await screen.findByText("Manual gate")).toBeInTheDocument();
  });

  it("renders a separation-of-duties lock with the derived_from reason", async () => {
    server.use(
      http.get(`${R}/hitl-tasks`, () =>
        HttpResponse.json([
          synthTask({
            task_id: "sod1",
            title: "Approve gate",
            hitl_mode: "manual",
            role: "role.payments.ops_analyst",
            allowed_decisions: ["complete", "escalate"],
            sod: { excluded_users: ["analyst-1"], derived_from: ["distinct_actor: analyst-1 already acted on Task_Draft"] },
          }),
        ]),
      ),
    );
    renderApp("/inbox", "analyst-1");
    const row = await screen.findByLabelText(/Approve gate/i);
    expect(row.querySelector('[aria-label*="already acted"]')).toBeTruthy();
  });
});

describe("Task detail — review_after decide flow", () => {
  it("claims then approves, producing an immutable decision record", async () => {
    let task = synthTask({ task_id: "flow1", status: "open" });
    server.use(
      ...railHandlers(),
      http.get(`${R}/hitl-tasks/flow1`, () => HttpResponse.json(task)),
      http.post(`${R}/hitl-tasks/flow1/claim`, () => {
        task = { ...task, status: "claimed", assignee: "analyst-1" } as typeof task;
        return HttpResponse.json(task);
      }),
      http.post(`${R}/hitl-tasks/flow1/decide`, async ({ request }) => {
        const body = (await request.json()) as any;
        task = { ...task, status: "decided", decision: { decision: body.decision, decided_by: "analyst-1", decided_at: "2099-01-01T00:00:02Z", comment: null, edits: null, approved_action_ids: null } } as typeof task;
        return HttpResponse.json(task);
      }),
    );
    const user = userEvent.setup();
    renderApp("/inbox/flow1", "analyst-1");

    await user.click(await screen.findByRole("button", { name: /claim task/i }));
    await user.click(await screen.findByRole("button", { name: /^approve$/i }));

    await waitFor(() => expect(screen.getByText(/Decision record/i)).toBeInTheDocument());
    expect(screen.getByText(/Immutable/i)).toBeInTheDocument();
  });
});

describe("Task detail — backend 403 on claim", () => {
  afterEach(() => vi.restoreAllMocks());

  async function claimReturns403(detail: unknown) {
    const errSpy = vi.spyOn(toast, "error").mockImplementation(() => "" as never);
    // Client-side eligible (role matches, not SoD-locked) so the claim button shows.
    const task = synthTask({ task_id: "f403", status: "open", role: "role.payments.ops_analyst" });
    server.use(
      ...railHandlers(),
      http.get(`${R}/hitl-tasks/f403`, () => HttpResponse.json(task)),
      http.post(`${R}/hitl-tasks/f403/claim`, () =>
        HttpResponse.json({ detail }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/inbox/f403", "analyst-1");
    await user.click(await screen.findByRole("button", { name: /claim task/i }));
    return errSpy;
  }

  it("surfaces the SoD reason string from the runtime", async () => {
    const errSpy = await claimReturns403("user 'usr-analyst' is excluded by separation-of-duties");
    await waitFor(() =>
      expect(errSpy).toHaveBeenCalledWith(expect.stringMatching(/separation-of-duties/i)),
    );
  });

  it("surfaces the missing-role reason string from the runtime", async () => {
    const errSpy = await claimReturns403("caller lacks required role 'role.payments.ops_approver'");
    await waitFor(() =>
      expect(errSpy).toHaveBeenCalledWith(expect.stringMatching(/lacks required role/i)),
    );
  });
});
