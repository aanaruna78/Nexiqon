import { Suspense } from "react";

import { AssistantDetail } from "@/components/assistants/assistant-detail";

export default async function Page({ params }: PageProps<"/assistants/[name]">) {
  const { name } = await params;
  return (
    <Suspense>
      <AssistantDetail name={name} />
    </Suspense>
  );
}
