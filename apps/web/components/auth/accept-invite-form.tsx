"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { AuthCard, Field, FormError } from "@/components/auth/auth-card";
import { useAuthSubmit } from "@/components/auth/use-auth-submit";
import { Button } from "@/components/ui/button";

const schema = z.object({
  password: z.string().min(10, "Use at least 10 characters"),
});
type Values = z.infer<typeof schema>;

export function AcceptInviteForm() {
  const token = useSearchParams().get("token");
  const { error, submit } = useAuthSubmit("accept-invite");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  if (!token) {
    return (
      <AuthCard
        eyebrow="Invitation"
        title="This invite link is invalid"
        description="It may be incomplete, expired, or already used. Ask your agency admin to send a new invite."
        footer={
          <Link href="/login" className="text-foreground underline underline-offset-4">
            Go to sign in
          </Link>
        }
      />
    );
  }

  return (
    <AuthCard
      eyebrow="Invitation"
      title="Join your team"
      description="Set a password to accept the invite. If you already have an account, enter your existing password."
    >
      <form
        noValidate
        onSubmit={handleSubmit(({ password }) => submit({ token, password }))}
        className="flex flex-col gap-4"
      >
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <FormError message={error} />
        <Button type="submit" size="lg" className="h-11 w-full" disabled={isSubmitting}>
          {isSubmitting ? "Joining…" : "Join team"}
        </Button>
      </form>
    </AuthCard>
  );
}
