"use client";

import { useTranslations } from "next-intl";

import { StatusBadge } from "@/components/visual/status-badge";
import { type EvalRun, passTone, percent } from "@/lib/evaluation";

/** A run's state: progress while asking, its pass rate when done. */
export function RunStatus({ run, threshold = 0.8 }: { run: EvalRun; threshold?: number }) {
  const t = useTranslations("evaluations");
  if (run.status === "queued" || run.status === "running") {
    return (
      <StatusBadge tone="sky" live>
        {t("asking", { done: run.done_count, total: run.case_count })}
      </StatusBadge>
    );
  }
  if (run.status === "failed") return <StatusBadge tone="rose">{run.error === "changed_during_run" ? t("changedDuringRun") : t("failed")}</StatusBadge>;
  if (!run.scorecard) return <StatusBadge tone="slate">—</StatusBadge>;
  return <StatusBadge tone={passTone(run.scorecard.pass_rate, threshold)}>{t("passing", { score: percent(run.scorecard.pass_rate) })}</StatusBadge>;
}
