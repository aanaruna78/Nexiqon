"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Globe, KeyRound, Plus, Server } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { useStudio } from "@/components/shell/studio-context";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";

interface ApiKey {
  id: string;
  name: string;
  kind: "server" | "widget";
  prefix: string;
  roles: string[];
  allowed_origins: string[];
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export function ApiKeysPage() {
  const t = useTranslations("apiKeys");
  const tc = useTranslations("common");
  const format = useFormatter();
  // Explicit "now" (refreshed every minute) keeps "5 minutes ago" consistent and up to date.
  const now = useNow({ updateInterval: 60_000 });
  const params = useSearchParams();
  const { isAdmin } = useStudio();
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [createOpen, setCreateOpen] = useState(params.get("create") === "1");
  const [secret, setSecret] = useState<string | null>(null);
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api<ApiKey[]>("identity/v1/api-keys") });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`identity/v1/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("revoked"));
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError,
  });

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        icon={KeyRound}
        tone="amber"
        actions={isAdmin ? (
          <Button onClick={() => setCreateOpen(true)} data-testid="create-key" className="shadow-sm">
            <Plus className="size-4" aria-hidden="true" />
            {t("create")}
          </Button>
        ) : null}
      />
      <CreateKeyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(value) => {
          setSecret(value);
          void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
        }}
      />
      <SecretDialog secret={secret} onDone={() => setSecret(null)} />
      {keys.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !keys.data?.length ? (
        <EmptyState icon={KeyRound} tone="amber" title={t("empty")} />
      ) : (
        <div className="nx-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{tc("name")}</TableHead>
              <TableHead className="hidden sm:table-cell">{t("kind")}</TableHead>
              <TableHead className="hidden lg:table-cell">{t("prefix")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("roles")}</TableHead>
              <TableHead className="hidden md:table-cell">{t("lastUsed")}</TableHead>
              <TableHead className="w-24"><span className="sr-only">{tc("actions")}</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="nx-stagger">
            {keys.data.map((k) => (
              <TableRow key={k.id} data-testid={`key-${k.name}`}>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <IconTile icon={k.kind === "widget" ? Globe : Server} tone={k.kind === "widget" ? "sky" : "navy"} size="sm" />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{k.name}</div>
                      <div className="text-xs text-muted-foreground sm:hidden">{t(`kinds.${k.kind}`)}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="hidden sm:table-cell">{t(`kinds.${k.kind}`)}</TableCell>
                <TableCell className="hidden lg:table-cell"><code dir="ltr" className="rounded bg-muted px-1.5 py-0.5 text-xs">nxq_{k.kind[0]}_{k.prefix}_…</code></TableCell>
                <TableCell className="hidden md:table-cell">{k.roles.join(", ")}</TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {k.last_used_at ? format.relativeTime(new Date(k.last_used_at), now) : tc("never")}
                </TableCell>
                <TableCell>
                  {k.revoked_at ? (
                    <StatusBadge tone="slate">{t("revokedLabel")}</StatusBadge>
                  ) : isAdmin ? (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="sm" aria-label={`${t("revoke")}: ${k.name}`}>{t("revoke")}</Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>{t("revokeTitle", { name: k.name })}</AlertDialogTitle>
                          <AlertDialogDescription>{t("revokeBody")}</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
                          <AlertDialogAction onClick={() => revoke.mutate(k.id)}>{t("revoke")}</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </div>
      )}
    </div>
  );
}

function CreateKeyDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (secret: string) => void }) {
  const t = useTranslations("apiKeys");
  const tc = useTranslations("common");
  const onError = useErrorToast();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"server" | "widget">("server");
  const [role, setRole] = useState("member");
  const [origins, setOrigins] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api<{ secret: string }>("identity/v1/api-keys", {
        method: "POST",
        json: kind === "widget"
          ? { name, kind, allowed_origins: origins.split(/\s+/).filter(Boolean) }
          : { name, kind, roles: [role] },
      }),
    onSuccess: (data) => {
      toast.success(t("created"));
      setName("");
      setOrigins("");
      onOpenChange(false);
      onCreated(data.secret);
    },
    onError,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("createTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="key-name">{tc("name")}</Label>
            <Input id="key-name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("kind")}</legend>
            {(["server", "widget"] as const).map((k) => (
              <label key={k} className="flex cursor-pointer gap-3 rounded-md border p-3 has-[:checked]:border-primary has-[:checked]:bg-accent/40">
                <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} className="mt-1 accent-[var(--primary)]" />
                <span>
                  <span className="block font-medium">{t(`kinds.${k}`)}</span>
                  <span className="block text-sm text-muted-foreground">{t(`kindHelp.${k}`)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {kind === "server" ? (
            <div className="space-y-2">
              <Label htmlFor="key-role">{t("roles")}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="key-role" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["member", "editor", "end_user"].map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="key-origins">{t("origins")}</Label>
              <Textarea id="key-origins" dir="ltr" required rows={3} aria-describedby="key-origins-help" value={origins} onChange={(e) => setOrigins(e.target.value)} />
              <p id="key-origins-help" className="text-sm text-muted-foreground">{t("originsHelp")}</p>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit" disabled={create.isPending || !name}>{t("create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SecretDialog({ secret, onDone }: { secret: string | null; onDone: () => void }) {
  const t = useTranslations("apiKeys");
  const tc = useTranslations("common");
  return (
    <Dialog open={secret !== null} onOpenChange={() => undefined}>
      <DialogContent onEscapeKeyDown={(e) => e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()} showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{t("secretTitle")}</DialogTitle>
          <DialogDescription>{t("secretBody")}</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <Input readOnly dir="ltr" value={secret ?? ""} aria-label={t("prefix")} className="font-mono text-xs" data-testid="key-secret" onFocus={(e) => e.target.select()} />
          <Button
            type="button"
            variant="outline"
            onClick={async () => {
              await navigator.clipboard.writeText(secret ?? "");
              toast.success(tc("copied"));
            }}
          >
            <Copy className="size-4" aria-hidden="true" />
            {t("copySecret")}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onDone}>{t("stored")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
