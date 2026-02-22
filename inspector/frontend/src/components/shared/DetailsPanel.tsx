"use client";

interface Props {
  children: React.ReactNode;
}

/**
 * Responsive right-hand details panel.
 * On mobile it renders below the main content; on md+ it sits in the
 * second grid column with a fixed width.
 */
export default function DetailsPanel({ children }: Props) {
  return (
    <div className="border border-gray-200 p-2 overflow-auto min-w-0 md:min-w-[320px] md:max-w-[320px] lg:min-w-[380px] lg:max-w-[380px] xl:min-w-[420px] xl:max-w-[420px] 2xl:min-w-[480px] 2xl:max-w-[480px]">
      {children}
    </div>
  );
}
