import { ConfigEditor } from "@/components/settings/config-editor";

export default async function Page({ params }: PageProps<"/settings/configuration/[kind]/[name]">) {
  const { kind, name } = await params;
  return <ConfigEditor kind={kind} name={name} />;
}
