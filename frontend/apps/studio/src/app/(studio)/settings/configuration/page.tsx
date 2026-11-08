import { Suspense } from "react";

import { ConfigurationPage } from "@/components/settings/configuration";

export default function Page() {
  return (
    <Suspense>
      <ConfigurationPage />
    </Suspense>
  );
}
