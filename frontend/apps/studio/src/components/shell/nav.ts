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
      { key: "home", href: "/", icon: House },
      { key: "assistants", href: "/assistants", icon: Bot, phase: "Phase 3" },
      { key: "knowledge", href: "/knowledge", icon: BookOpenText, phase: "Phase 2" },
      { key: "playground", href: "/playground", icon: FlaskConical, phase: "Phase 2–3" },
      { key: "domainPacks", href: "/domain-packs", icon: Package, phase: "Phase 3" },
    ],
  },
  {
    key: "operate",
    items: [
      { key: "conversations", href: "/conversations", icon: MessagesSquare, phase: "Phase 4" },
      { key: "insights", href: "/insights", icon: ChartLine, phase: "Phase 4" },
      { key: "evaluations", href: "/evaluations", icon: ClipboardCheck, phase: "Phase 4" },
      { key: "actions", href: "/actions", icon: Blocks, phase: "Phase 3" },
    ],
  },
  {
    key: "admin",
    items: [
      { key: "members", href: "/settings/members", icon: Users },
      { key: "apiKeys", href: "/settings/api-keys", icon: KeyRound },
      { key: "configuration", href: "/settings/configuration", icon: Settings2 },
      { key: "audit", href: "/settings/audit", icon: ScrollText },
      { key: "organization", href: "/settings/organization", icon: ShieldCheck },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

export function activeItem(pathname: string): NavItem | undefined {
  return [...ALL_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)));
}
