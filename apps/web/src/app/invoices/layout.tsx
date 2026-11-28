import { AppHeader } from "@/components/app-header";

export default function InvoicesLayout({ children }: LayoutProps<"/invoices">) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 p-6">
      <AppHeader />
      {children}
    </div>
  );
}
