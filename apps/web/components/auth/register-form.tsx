"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { AuthCard, Field, FormError } from "@/components/auth/auth-card";
import { useAuthSubmit } from "@/components/auth/use-auth-submit";
import { Button } from "@/components/ui/button";

const schema = z.object({
  tenant_name: z.string().trim().min(1, "Enter your agency name"),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(10, "Use at least 10 characters"),
});
type Values = z.infer<typeof schema>;

export function RegisterForm() {
  const { error, submit } = useAuthSubmit("register");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <AuthCard
      eyebrow="Create account"
      title="Create your agency"
      description="Start a workspace for your team and clients."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
        <Field
          id="tenant_name"
          label="Agency name"
          autoComplete="organization"
          error={errors.tenant_name?.message}
          {...register("tenant_name")}
        />
        <Field
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <FormError message={error} />
        <Button type="submit" size="lg" className="h-11 w-full cursor-pointer" disabled={isSubmitting}>
          {isSubmitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}
