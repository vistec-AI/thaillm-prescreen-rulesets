"use client";

import Image from "next/image";

export default function Footer() {
  return (
    <footer className="mt-2 pt-1.5 border-t border-gray-200 flex items-center justify-between gap-2 flex-wrap text-sm">
      <div>
        Developed by <b>VISAI</b> &bull; Sponsored by <b>VISTEC</b> &amp; <b>BDI</b>
      </div>
      <div className="flex items-center gap-3">
        <Image src="/brand/visai.png" alt="VISAI" width={60} height={22} className="h-[22px] w-auto object-contain" />
        <Image src="/brand/vistec.png" alt="VISTEC" width={60} height={22} className="h-[22px] w-auto object-contain" />
        <Image src="/brand/bdi.webp" alt="BDI" width={70} height={26} className="h-[26px] w-auto object-contain" />
      </div>
    </footer>
  );
}
