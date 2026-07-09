import { PageHeader } from "@/app/AppShell";
import { EmptyState } from "@/components/primitives";
import { Construction } from "lucide-react";

/** Placeholder for screens implemented in later milestones. */
export function StubScreen({ title, milestone }: { title: string; milestone: string }) {
  return (
    <>
      <PageHeader title={title} description={`Implemented in ${milestone}.`} />
      <EmptyState
        icon={<Construction className="size-6" />}
        title={`${title} — coming in ${milestone}`}
        description="This screen is scaffolded. The interactive implementation lands in its milestone."
      />
    </>
  );
}
