import { Suspense } from "react";

import { ConversationsPage } from "@/components/operate/conversations-page";

export default function Page() {
  return (
    <Suspense>
      <ConversationsPage />
    </Suspense>
  );
}
