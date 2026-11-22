import { Suspense } from "react";

import { MembersPage } from "@/components/settings/members";

export default function Page() {
  return (
    <Suspense>
      <MembersPage />
    </Suspense>
  );
}
