import { redirect } from "next/navigation";
export default function AlertsPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (typeof value === "string") params.set(key, value);
  }
  params.set("warning", "ATTENTION");
  redirect(`/?${params}`);
}
