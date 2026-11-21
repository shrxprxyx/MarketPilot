"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Field, FormError } from "@/components/auth/auth-card";
import { SpendBar } from "@/components/budget/spend-bar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import { useBudget, useSaveBudget, type Budget } from "@/lib/queries/budget";

// Blank means "no budget". Otherwise a positive amount with at most 2 decimals.
const schema = z.object({
  amount: z
    .string()
    .trim()
    .refine(
      (v) => v === "" || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) > 0),
      "Enter an amount above 0, with at most 2 decimals",
    ),
  hard_stop: z.boolean(),
});
type Values = z.infer<typeof schema>;

const toValues = (b: Budget): Values => ({
  amount: b.monthly_budget_usd === null ? "" : String(Number(b.monthly_budget_usd)),
  hard_stop: b.hard_stop,
});

function BudgetForm({ budget }: { budget: Budget }) {
  const save = useSaveBudget();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(budget) });

  async function submit(values: Values) {
    setServerError(null);
    const amount = values.amount === "" ? null : Number(values.amount);
    try {
      // A hard stop without a budget would do nothing, so it is not stored.
      await save.mutateAsync({ monthly_budget_usd: amount, hard_stop: amount === null ? false : values.hard_stop });
      toast.success("Budget saved");
      reset({ amount: values.amount, hard_stop: amount === null ? false : values.hard_stop });
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit(submit)} className="flex max-w-md flex-col gap-4">
      <Field
        id="budget-amount"
        label="Monthly budget (USD)"
        inputMode="decimal"
        placeholder="No budget"
        error={errors.amount?.message}
        {...register("amount")}
      />
      <label className="flex cursor-pointer items-start gap-3 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 cursor-pointer" {...register("hard_stop")} />
        <span>
          Stop AI calls when the budget is reached
          <span className="block text-xs text-muted-foreground">
            Without this you only get a warning at 80% and when the budget is reached.
          </span>
        </span>
      </label>
      <FormError message={serverError} />
      <div>
        <Button type="submit" size="lg" className="h-11 cursor-pointer px-6" disabled={!isDirty || isSubmitting}>
          {isSubmitting ? "Saving…" : "Save budget"}
        </Button>
      </div>
    </form>
  );
}

export function BudgetSection() {
  const role = useSession((s) => s.me?.role);
  const canView = role === "admin" || role === "manager";
  const { data, isLoading, isError } = useBudget(canView);

  if (!canView) return null;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Budget
        </p>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Set a monthly limit on AI spend. You get a warning at 80%, and can optionally stop AI
          calls once it is reached. Spend is estimated from model prices; calls to models without
          a known price are not counted.
        </p>
      </div>
      {isLoading ? (
        <Skeleton data-testid="budget-skeleton" className="h-24 w-full max-w-md" />
      ) : isError || !data ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load the budget. Try again later.</p>
      ) : (
        <>
          <SpendBar budget={data} />
          {role === "admin" ? (
            <BudgetForm key={JSON.stringify(data)} budget={data} />
          ) : (
            <p className="text-sm text-muted-foreground">Only admins can change the budget.</p>
          )}
        </>
      )}
    </section>
  );
}
