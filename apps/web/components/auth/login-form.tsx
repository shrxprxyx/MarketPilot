"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { AuthCard, Field, FormError } from "@/components/auth/auth-card";
import { useAuthSubmit } from "@/components/auth/use-auth-submit";
import { Button } from "@/components/ui/button";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

export function LoginForm() {
  const { error, submit } = useAuthSubmit("login");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <AuthCard
      eyebrow="Sign in"
      title="Welcome back"
      description="Sign in to your agency workspace."
      footer={
        <>
          New here?{" "}
          <Link href="/register" className="text-foreground underline-offset-4 hover:underline">
            Create an agency
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
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
          autoComplete="current-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <FormError message={error} />
        <Button type="submit" size="lg" className="h-11 w-full" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthCard>
  );
}
