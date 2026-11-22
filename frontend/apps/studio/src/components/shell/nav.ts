import type { Tone } from "@/components/visual/icon-tile";
import {
  Blocks,
  BookOpenText,
  Bot,
  ChartLine,
  ClipboardCheck,
  Cpu,
  FlaskConical,
  House,
  KeyRound,
  type LucideIcon,
  MessagesSquare,
  Package,
  ScrollText,
  Settings2,
  ShieldCheck,
  Users,
  Webhook,
} from "lucide-react";

export interface NavItem {
  key: string; // messages: nav.<key>
  href: string;
  icon: LucideIcon;
  tone: Tone;
  phase?: string; // shown on "coming soon" pages
}

export interface NavGroup {
  key: "build" | "operate" | "admin";
  items: NavItem[];
}

/** The Admin area's navigation. Everyone lands on the chat (/); people who build and run assistants
 * (owners, admins, editors) also reach Admin. Personal preferences live in /settings. */
export const NAV: NavGroup[] = [
  {
    key: "build",
    items: [
      { key: "overview", href: "/admin", icon: House, tone: "teal" },
      { key: "assistants", href: "/admin/assistants", icon: Bot, tone: "violet" },
      { key: "knowledge", href: "/admin/knowledge", icon: BookOpenText, tone: "sky" },
      { key: "playground", href: "/admin/playground", icon: FlaskConical, tone: "amber" },
      { key: "domainPacks", href: "/admin/domain-packs", icon: Package, tone: "teal" },
    ],
  },
  {
    key: "operate",
    items: [
      { key: "conversations", href: "/admin/conversations", icon: MessagesSquare, tone: "sky" },
      { key: "insights", href: "/admin/insights", icon: ChartLine, tone: "violet" },
      { key: "evaluations", href: "/admin/evaluations", icon: ClipboardCheck, tone: "amber" },
      { key: "actions", href: "/admin/actions", icon: Blocks, tone: "rose" },
    ],
  },
  {
    key: "admin",
    items: [
      { key: "members", href: "/admin/members", icon: Users, tone: "violet" },
      { key: "apiKeys", href: "/admin/api-keys", icon: KeyRound, tone: "amber" },
      { key: "models", href: "/admin/models", icon: Cpu, tone: "sky" },
      { key: "configuration", href: "/admin/configuration", icon: Settings2, tone: "teal" },
      { key: "audit", href: "/admin/audit", icon: ScrollText, tone: "sky" },
      { key: "webhooks", href: "/admin/webhooks", icon: Webhook, tone: "rose" },
      { key: "organization", href: "/admin/organization", icon: ShieldCheck, tone: "navy" },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

export function activeItem(pathname: string): NavItem | undefined {
  return [...ALL_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => (item.href === "/admin" ? pathname === "/admin" : pathname === item.href || pathname.startsWith(`${item.href}/`)));
}
