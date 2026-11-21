"use client";

import { useState } from "react";
import { useForm, useWatch, type Control, type UseFormRegister } from "react-hook-form";
import { toast } from "sonner";
import { FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { routeSchema, TASKS, type RouteValues, type TaskType } from "@/lib/ai/schemas";
import { ApiError } from "@/lib/api/problem";
import {
  useAiConnections,
  useAiRoutes,
  useSaveRoutes,
  type AiConnection,
  type AiRoute,
} from "@/lib/queries/ai";

type Row = {
  task_type: TaskType;
  connection_id: string;
  model: string;
  temperature: number;
  max_tokens: number;
  fallback_connection_id: string;
  fallback_model: string;
};
type FormValues = { rows: Row[] };

const TASK_HINTS: Record<TaskType, string> = {
  strategy: "Plans and strategy generation",
  content: "Posts, articles and copy",
  analysis: "Audits and analysis",
};

function buildRows(routes: AiRoute[]): Row[] {
  return TASKS.map((task) => {
    const r = routes.find((x) => x.task_type === task);
    return {
      task_type: task,
      connection_id: r?.connection_id ?? "",
      model: r?.model ?? "",
      temperature: r?.temperature ?? 0.7,
      max_tokens: r?.max_tokens ?? 2048,
      fallback_connection_id: r?.fallback_connection_id ?? "",
      fallback_model: r?.fallback_model ?? "",
    };
  });
}

function Cell({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      {children}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

function TaskRow({
  index,
  task,
  control,
  register,
  connections,
  models,
  errors,
}: {
  index: number;
  task: TaskType;
  control: Control<FormValues>;
  register: UseFormRegister<FormValues>;
  connections: AiConnection[];
  models: Record<string, string[]>;
  errors: Partial<Record<keyof Row, string>>;
}) {
  const connectionId = useWatch({ control, name: `rows.${index}.connection_id` });
  const listId = `models-${task}`;
  const options = (
    <>
      <option value="">Choose a connection</option>
      {connections.map((c) => (
        <option key={c.id} value={c.id}>
          {c.label}
        </option>
      ))}
    </>
  );
  return (
    <div className="py-6">
      <div className="mb-4">
        <p className="font-medium capitalize">{task}</p>
        <p className="text-sm text-muted-foreground">{TASK_HINTS[task]}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Cell label="Connection" error={errors.connection_id}>
          <Select aria-label={`${task} connection`} {...register(`rows.${index}.connection_id`)}>
            {options}
          </Select>
        </Cell>
        <Cell label="Model" error={errors.model}>
          <Input
            aria-label={`${task} model`}
            list={listId}
            autoComplete="off"
            className="h-11 bg-white/[0.03]"
            {...register(`rows.${index}.model`)}
          />
          <datalist id={listId}>
            {(models[connectionId] ?? []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </Cell>
        <Cell label="Temperature" error={errors.temperature}>
          <Input
            type="number"
            step="0.1"
            aria-label={`${task} temperature`}
            className="h-11 bg-white/[0.03]"
            {...register(`rows.${index}.temperature`, { valueAsNumber: true })}
          />
        </Cell>
        <Cell label="Max tokens" error={errors.max_tokens}>
          <Input
            type="number"
            aria-label={`${task} max tokens`}
            className="h-11 bg-white/[0.03]"
            {...register(`rows.${index}.max_tokens`, { valueAsNumber: true })}
          />
        </Cell>
        <Cell label="Fallback connection (optional)">
          <Select
            aria-label={`${task} fallback connection`}
            {...register(`rows.${index}.fallback_connection_id`)}
          >
            <option value="">None</option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </Select>
        </Cell>
        <Cell label="Fallback model" error={errors.fallback_model}>
          <Input
            aria-label={`${task} fallback model`}
            autoComplete="off"
            className="h-11 bg-white/[0.03]"
            {...register(`rows.${index}.fallback_model`)}
          />
        </Cell>
      </div>
    </div>
  );
}

function RoutingForm({
  connections,
  routes,
  testedModels,
}: {
  connections: AiConnection[];
  routes: AiRoute[];
  testedModels: Record<string, string[]>;
}) {
  const save = useSaveRoutes();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    clearErrors,
    reset,
    getValues,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<FormValues>({ defaultValues: { rows: buildRows(routes) } });

  async function submit({ rows }: FormValues) {
    setServerError(null);
    clearErrors();
    const payload: RouteValues[] = [];
    let invalid = false;
    rows.forEach((row, i) => {
      // A task with neither connection nor model is simply left unrouted.
      if (!row.connection_id && !row.model.trim()) return;
      const candidate: Record<string, unknown> = {
        task_type: row.task_type,
        connection_id: row.connection_id,
        model: row.model,
        temperature: row.temperature,
        max_tokens: row.max_tokens,
      };
      if (row.fallback_connection_id) candidate.fallback_connection_id = row.fallback_connection_id;
      if (row.fallback_model.trim()) candidate.fallback_model = row.fallback_model.trim();
      const parsed = routeSchema.safeParse(candidate);
      if (!parsed.success) {
        invalid = true;
        for (const issue of parsed.error.issues) {
          setError(`rows.${i}.${String(issue.path[0])}` as `rows.${number}.model`, {
            message: issue.message,
          });
        }
        return;
      }
      payload.push(parsed.data);
    });
    if (invalid || payload.length === 0) return;
    try {
      await save.mutateAsync(payload);
      toast.success("Routing saved");
      reset(getValues());
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit(submit)}>
      <div className="divide-y border-y">
        {TASKS.map((task, i) => (
          <TaskRow
            key={task}
            index={i}
            task={task}
            control={control}
            register={register}
            connections={connections}
            models={testedModels}
            errors={Object.fromEntries(
              Object.entries(errors.rows?.[i] ?? {}).map(([k, v]) => [k, (v as { message?: string } | undefined)?.message]),
            )}
          />
        ))}
      </div>
      <div className="mt-6 flex flex-col gap-4">
        <FormError message={serverError} />
        <div>
          <Button type="submit" size="lg" className="h-11 px-6" disabled={!isDirty || isSubmitting}>
            {isSubmitting ? "Saving…" : "Save routing"}
          </Button>
        </div>
      </div>
    </form>
  );
}

export function RoutingSection({ testedModels }: { testedModels: Record<string, string[]> }) {
  const connections = useAiConnections(true);
  const routes = useAiRoutes(true);

  return (
    <section>
      <h2 className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        Task routing
      </h2>
      {connections.isLoading || routes.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : !connections.data || connections.data.length === 0 ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          Add a connection first, then choose which model handles each task.
        </p>
      ) : (
        <RoutingForm
          // Remount when the server data changes (e.g. a connection was deleted) so the form
          // never keeps ids the server has dropped.
          key={JSON.stringify([connections.data.map((c) => c.id), routes.data])}
          connections={connections.data}
          routes={routes.data ?? []}
          testedModels={testedModels}
        />
      )}
    </section>
  );
}
