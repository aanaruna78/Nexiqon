import { Suspense } from "react";

import { ActionsPage } from "@/components/actions/actions-page";

export default function Page() {
  return (
    <Suspense>
      <ActionsPage />
    </Suspense>
  );
}
