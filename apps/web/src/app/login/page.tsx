import { login } from "@/app/actions";
import { LoginForm } from "@/components/login-form";

export const metadata = { title: "Log in · InvoiceGuard" };

export default function LoginPage() {
  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-4 p-6">
      <h1 className="font-heading text-2xl font-semibold">InvoiceGuard</h1>
      <p className="text-sm text-muted-foreground">
        Log in with a seeded reviewer account. There is no sign-up.
      </p>
      <LoginForm login={login} />
    </main>
  );
}
