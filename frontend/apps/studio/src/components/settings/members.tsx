"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus, Users } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";

export interface Member {
  id: string;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  role: "owner" | "admin" | "editor" | "member";
  status: "invited" | "active" | "disabled";
  created_at: string;
}

const ROLES = ["owner", "admin", "editor", "member"] as const;

export function MembersPage() {
  const t = useTranslations("members");
  const tc = useTranslations("common");
  const format = useFormatter();
  const params = useSearchParams();
  const { isAdmin, isOwner, user } = useStudio();
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [inviteOpen, setInviteOpen] = useState(params.get("invite") === "1");
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("identity/v1/members") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["members"] });

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => api(`identity/v1/members/${id}`, { method: "PATCH", json: { role } }),
    onSuccess: () => {
      toast.success(t("roleUpdated"));
      void refresh();
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`identity/v1/members/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("removed"));
      void refresh();
    },
    onError,
  });

  const assignable = isOwner ? ROLES : ROLES.filter((r) => r !== "owner");

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          isAdmin ? (
            <Button onClick={() => setInviteOpen(true)} data-testid="invite-member">
              <UserPlus className="size-4" aria-hidden="true" />
              {t("invite")}
            </Button>
          ) : null
        }
      />
      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} roles={assignable} onInvited={refresh} />
      {members.isLoading ? (
        <div className="space-y-2" aria-busy="true" aria-label={tc("loading")}>
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : !members.data?.length ? (
        <EmptyState icon={Users} title={t("empty")} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{tc("name")}</TableHead>
              <TableHead>{tc("role")}</TableHead>
              <TableHead>{tc("status")}</TableHead>
              <TableHead>{tc("created")}</TableHead>
              <TableHead className="w-12"><span className="sr-only">{tc("actions")}</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.data.map((m) => {
              const label = m.display_name ?? m.email ?? m.id;
              const isMe = !!m.email && m.email === user.email;
              const editable = isAdmin && (m.role !== "owner" || isOwner);
              return (
                <TableRow key={m.id} data-testid={`member-${m.email}`}>
                  <TableCell>
                    <div className="font-medium">
                      {label} {isMe ? <span className="text-muted-foreground">({t("you")})</span> : null}
                    </div>
                    {m.display_name && m.email ? <div className="text-sm text-muted-foreground">{m.email}</div> : null}
                  </TableCell>
                  <TableCell>
                    {editable ? (
                      <Select value={m.role} onValueChange={(role) => changeRole.mutate({ id: m.id, role })}>
                        <SelectTrigger className="w-36" aria-label={`${t("changeRole")}: ${label}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {assignable.map((r) => (
                            <SelectItem key={r} value={r}>{t(`roles.${r}`)}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      t(`roles.${m.role}`)
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={m.status === "active" ? "secondary" : "outline"}>{t(`statuses.${m.status}`)}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{format.dateTime(new Date(m.created_at), { dateStyle: "medium" })}</TableCell>
                  <TableCell>
                    {editable ? (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label={`${t("remove")}: ${label}`}>
                            <Trash2 className="size-4" aria-hidden="true" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>{t("removeTitle", { name: label })}</AlertDialogTitle>
                            <AlertDialogDescription>{t("removeBody")}</AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
                            <AlertDialogAction onClick={() => remove.mutate(m.id)}>{tc("remove")}</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    ) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function InviteDialog({ open, onOpenChange, roles, onInvited }: { open: boolean; onOpenChange: (o: boolean) => void; roles: readonly string[]; onInvited: () => void }) {
  const t = useTranslations("members");
  const tc = useTranslations("common");
  const onError = useErrorToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const invite = useMutation({
    mutationFn: () => api("identity/v1/members", { method: "POST", json: { email, role } }),
    onSuccess: () => {
      toast.success(t("invited", { email }));
      setEmail("");
      onOpenChange(false);
      onInvited();
    },
    onError,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("inviteTitle")}</DialogTitle>
            <DialogDescription>{t("inviteDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="invite-email">{tc("email")}</Label>
            <Input id="invite-email" type="email" dir="ltr" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-role">{tc("role")}</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id="invite-role" className="w-full" aria-describedby="invite-role-help">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r} value={r}>{t(`roles.${r}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p id="invite-role-help" className="text-sm text-muted-foreground">{t(`roleHelp.${role}`)}</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit" disabled={invite.isPending || !email.includes("@")}>{t("sendInvite")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
