"use client";

import { usePathname } from "next/navigation";

const Header = () => {
  const pathname = usePathname();
  if (pathname === "/") return null;

  return (
    <header className="px-4 pb-3 pt-3">
      <div className="mt-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[#1f1f1f]">카카오톡</h1>
        <div className="flex items-center gap-3 text-gray-600">
          <button
            className="w-9 h-9 flex items-center justify-center rounded-full bg-[#f3f4f6] hover:bg-[#e7e9ee] transition-colors"
            aria-label="검색"
          >
            <span className="text-sm">🔍</span>
          </button>
          <button
            className="w-9 h-9 flex items-center justify-center rounded-full bg-[#f3f4f6] hover:bg-[#e7e9ee] transition-colors"
            aria-label="친구 추가"
          >
            <span className="text-sm">＋</span>
          </button>
        </div>
      </div>
    </header>
  );
};

export default Header;
