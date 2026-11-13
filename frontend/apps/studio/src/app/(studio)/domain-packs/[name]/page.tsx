import { Suspense } from "react";

import { PackEditor } from "@/components/packs/pack-editor";

export default async function Page({ params }: PageProps<"/domain-packs/[name]">) {
  const { name } = await params;
  return (
    <Suspense>
      <PackEditor name={name} />
    </Suspense>
  );
}
