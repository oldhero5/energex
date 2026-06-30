import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { roleFromSession } from "@/lib/api";
import { NavRail } from "@/components/nav-rail";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect("/login");
  }

  const role = roleFromSession(session.access_token);

  // active section is fixed until the other section routes exist
  const active = "overview";

  return (
    <div className="flex h-screen overflow-hidden">
      <NavRail role={role} active={active} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center border-b border-line-soft bg-panel px-4">
          <span className="text-sm text-muted">Energex Observer</span>
          <span className="ml-auto text-xs text-muted">
            {session.user.email} · {role}
          </span>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
