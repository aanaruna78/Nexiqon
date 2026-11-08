"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

import { openCommandMenu } from "./command-menu";
import { activeItem, NAV } from "./nav";

export function Header() {
  const t = useTranslations();
  const pathname = usePathname();
  const item = activeItem(pathname);
  const group = NAV.find((g) => g.items.some((i) => i.key === item?.key));
  const detail =
    item && pathname !== item.href
      ? decodeURIComponent(pathname.slice(item.href.length + 1))
          .split("/")
          .map((part) => (part === "new" ? t("common.add") : part.replace(/_/g, " ")))
          .join(" › ")
      : null;

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <SidebarTrigger className="-ms-1" aria-label={t("shell.toggleSidebar")} />
      <Separator orientation="vertical" className="me-2 h-4" />
      <Breadcrumb aria-label={t("shell.breadcrumb")} className="min-w-0 flex-1">
        <BreadcrumbList>
          {group && group.key !== "build" ? (
            <>
              <BreadcrumbItem className="hidden md:block">{t(`nav.${group.key}`)}</BreadcrumbItem>
              <BreadcrumbSeparator className="hidden md:block" />
            </>
          ) : null}
          {item ? (
            detail ? (
              <>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link href={item.href}>{t(`nav.${item.key}`)}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator />
                <BreadcrumbItem>
                  <BreadcrumbPage className="truncate">{detail}</BreadcrumbPage>
                </BreadcrumbItem>
              </>
            ) : (
              <BreadcrumbItem>
                <BreadcrumbPage>{t(`nav.${item.key}`)}</BreadcrumbPage>
              </BreadcrumbItem>
            )
          ) : null}
        </BreadcrumbList>
      </Breadcrumb>
      <Button variant="outline" size="sm" className="gap-2 text-muted-foreground" onClick={openCommandMenu} data-testid="command-button">
        <Search className="size-4" aria-hidden="true" />
        <span className="hidden sm:inline">{t("shell.openCommand")}</span>
        <kbd className="pointer-events-none hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
      </Button>
    </header>
  );
}
