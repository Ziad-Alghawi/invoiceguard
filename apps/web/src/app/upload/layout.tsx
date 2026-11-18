import { AppHeader } from "@/components/app-header";

export default function UploadLayout({ children }: LayoutProps<"/upload">) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-6">
      <AppHeader />
      {children}
    </div>
  );
}
