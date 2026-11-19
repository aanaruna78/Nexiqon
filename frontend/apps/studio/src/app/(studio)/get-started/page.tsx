import { Suspense } from "react";

import { SetupGuide } from "@/components/onboarding/setup-guide";

export default function Page() {
  return (
    <Suspense>
      <SetupGuide />
    </Suspense>
  );
}
