// features/copilot/CopilotFlow.tsx — the default onboarding front door (/registry/onboard). Start → Generating →
// Review+Chat. The uploaded BPMN is stashed per-session so the diagram survives a refresh (no backend fetch for
// an onboarding session's raw XML yet — an async+poll/BPMN-GET seam would go here if generation latency grows).
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/app/AppShell";
import { getOnboardingSession, type OnboardingSession } from "@/api/services/registry";
import { CopilotStart } from "./CopilotStart";
import { CopilotReview } from "./CopilotReview";
import { CopilotChat } from "./CopilotChat";

const bpmnKey = (id: string) => `copilot-bpmn:${id}`;

export function CopilotFlow() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  if (!sessionId) {
    return (
      <CopilotStart
        onGenerated={(s, xml) => {
          try { sessionStorage.setItem(bpmnKey(s.session_id), xml); } catch { /* private mode — diagram just won't persist */ }
          navigate(`/registry/onboard/${s.session_id}`);
        }}
      />
    );
  }
  return <CopilotReviewScreen sessionId={sessionId} />;
}

function CopilotReviewScreen({ sessionId }: { sessionId: string }) {
  const query = useQuery({ queryKey: ["onboarding", sessionId], queryFn: () => getOnboardingSession(sessionId) });
  const [session, setSession] = useState<OnboardingSession | null>(null);
  useEffect(() => { if (query.data) setSession(query.data); }, [query.data]);

  if (query.isError) {
    return <PageHeader title="Process not found" description="This onboarding session could not be loaded." />;
  }
  if (!session) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const xml = (() => { try { return sessionStorage.getItem(bpmnKey(sessionId)) ?? undefined; } catch { return undefined; } })();

  return (
    <div>
      <PageHeader title="Review your process" description="Read the design in plain language, refine it by chatting, then approve it to go live." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <CopilotReview session={session} xml={xml} />
        <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-8rem)]">
          <CopilotChat session={session} onUpdated={setSession} />
        </div>
      </div>
    </div>
  );
}
