"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { StudioMembership } from "@/app/api/session/route";
import type { SessionUser } from "@/lib/server/session";

interface StudioContextValue {
  user: SessionUser;
  active: StudioMembership;
  /** UI hint only: the gateway and OPA enforce permissions on every call. */
  isAdmin: boolean;
  isOwner: boolean;
}

const StudioContext = createContext<StudioContextValue | null>(null);

export function StudioProvider({ user, active, children }: { user: SessionUser; active: StudioMembership; children: ReactNode }) {
  const value = { user, active, isAdmin: ["owner", "admin"].includes(active.role), isOwner: active.role === "owner" };
  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error("useStudio must be used inside the Studio shell");
  return ctx;
}
