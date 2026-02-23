"use client";

/** Severity badge color map keyed by severity ID. */
const SEV_STYLES: Record<string, string> = {
  sev003:   "bg-red-100 text-red-800",
  sev002_5: "bg-orange-100 text-orange-800",
  sev002:   "bg-yellow-100 text-yellow-800",
  sev001:   "bg-green-100 text-green-800",
};

/** Generic type badge (used for demographic field types). */
const TYPE_STYLE = "bg-blue-100 text-blue-800";

interface Props {
  /** The severity ID (sev001–sev003) or "type" for a generic blue badge. */
  variant: string;
  children: React.ReactNode;
}

export default function Badge({ variant, children }: Props) {
  const color = variant === "type" ? TYPE_STYLE : (SEV_STYLES[variant] ?? "bg-gray-100 text-gray-700");
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold ${color}`}>
      {children}
    </span>
  );
}
