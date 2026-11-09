import { Suspense } from "react";

import { Playground } from "@/components/playground/playground";

export default function Page() {
  return (
    <Suspense>
      <Playground />
    </Suspense>
  );
}
