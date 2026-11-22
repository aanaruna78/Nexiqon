import { Suspense } from "react";

import { TestSetDetail } from "@/components/evaluations/test-set-detail";

export default async function Page({ params }: PageProps<"/admin/evaluations/[id]">) {
  const { id } = await params;
  return (
    <Suspense>
      <TestSetDetail id={id} />
    </Suspense>
  );
}
