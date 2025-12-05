"use client";

import { useRouter } from "next/navigation";

const LandingContainer = () => {
  const router = useRouter();

  return (
    <div className="flex h-full items-center justify-center bg-white">
      <button
        onClick={() => router.push("/chat")}
        className="px-6 py-3 rounded-full bg-[#ffeb3b] text-[#1f1f1f] font-semibold shadow hover:brightness-95"
      >
        채팅으로 이동
      </button>
    </div>
  );
};

export default LandingContainer;
