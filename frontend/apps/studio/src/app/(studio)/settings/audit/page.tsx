import { Suspense } from "react";

import { AuditPage } from "@/components/settings/audit";

export default function Page() {
  return (
    <Suspense>
      <AuditPage />
    </Suspense>
  );
}
