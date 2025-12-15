"use client";

import Link from "next/link";


const LandingContainer = () => {

  return (
    <div className="flex h-full items-center justify-center bg-white">
      <Link href="/chat" className="px-6 py-3 rounded-full bg-[#ffeb3b] text-[#1f1f1f] font-semibold shadow hover:brightness-95">
        채팅으로 이동
      </Link>

    </div>
  );
};

export default LandingContainer;
