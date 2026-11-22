import { Suspense } from "react";

import { OrganizationPage } from "@/components/settings/organization";

export default function Page() {
  return (
    <Suspense>
      <OrganizationPage />
    </Suspense>
  );
}
