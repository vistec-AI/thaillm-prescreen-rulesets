"use client";

import Image from "next/image";

export default function Titlebar() {
  return (
    <div className="flex items-center gap-2 my-2">
      <Image src="/brand/thaillm.png" alt="ThaiLLM" width={28} height={28} className="object-contain" />
      <h3 className="text-lg font-semibold m-0">Prescreen Initial Assessment Rules Inspector</h3>
    </div>
  );
}
