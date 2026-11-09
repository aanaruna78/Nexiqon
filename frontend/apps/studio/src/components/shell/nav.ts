import type { Tone } from "@/components/visual/icon-tile";
import {
  Blocks,
  BookOpenText,
  Bot,
  ChartLine,
  ClipboardCheck,
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

/** Studio information architecture (docs/plan/UX.md §5). */
export const NAV: NavGroup[] = [
  {
    key: "build",
    items: [
      { key: "home", href: "/", icon: House, tone: "teal" },
      { key: "assistants", href: "/assistants", icon: Bot, tone: "violet", phase: "Phase 3" },
      { key: "knowledge", href: "/knowledge", icon: BookOpenText, tone: "sky" },
      { key: "playground", href: "/playground", icon: FlaskConical, tone: "amber" },
      { key: "domainPacks", href: "/domain-packs", icon: Package, tone: "teal", phase: "Phase 3" },
    ],
  },
  {
    key: "operate",
    items: [
      { key: "conversations", href: "/conversations", icon: MessagesSquare, tone: "sky", phase: "Phase 4" },
      { key: "insights", href: "/insights", icon: ChartLine, tone: "violet", phase: "Phase 4" },
      { key: "evaluations", href: "/evaluations", icon: ClipboardCheck, tone: "amber", phase: "Phase 4" },
      { key: "actions", href: "/actions", icon: Blocks, tone: "rose", phase: "Phase 3" },
    ],
  },
  {
    key: "admin",
    items: [
      { key: "members", href: "/settings/members", icon: Users, tone: "violet" },
      { key: "apiKeys", href: "/settings/api-keys", icon: KeyRound, tone: "amber" },
      { key: "configuration", href: "/settings/configuration", icon: Settings2, tone: "teal" },
      { key: "audit", href: "/settings/audit", icon: ScrollText, tone: "sky" },
      { key: "organization", href: "/settings/organization", icon: ShieldCheck, tone: "navy" },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

export function activeItem(pathname: string): NavItem | undefined {
  return [...ALL_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)));
}
