import { Suspense } from "react";

import { ApiKeysPage } from "@/components/settings/api-keys";

export default function Page() {
  return (
    <Suspense>
      <ApiKeysPage />
    </Suspense>
  );
}
