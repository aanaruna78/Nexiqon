import { CollectionDetail } from "@/components/knowledge/collection-detail";

export default async function Page({ params }: PageProps<"/admin/knowledge/[id]">) {
  const { id } = await params;
  return <CollectionDetail id={id} />;
}
